import json
from datetime import datetime


class XBRLRetriever:
    def __init__(self, company_ticker: str):
        self.company_ticker = company_ticker.upper()
        self.file_path = f"output/xbrl/raw/{self.company_ticker}/company_facts.json"
        self.data = self._load_json()
        
        # Define metric mappings from user-friendly terms to XBRL metric names
        self.metric_mappings = {
            'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'],
            'sales': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues'],
            'profit': ['NetIncomeLoss'],
            'income': ['NetIncomeLoss', 'OperatingIncomeLoss'],
            'earnings': ['NetIncomeLoss'],
            'net income': ['NetIncomeLoss'],
            'operating income': ['OperatingIncomeLoss'],
            'assets': ['Assets'],
            'liabilities': ['Liabilities'],
            'equity': ['StockholdersEquity'],
            'stockholders equity': ['StockholdersEquity'],
            'cash': ['CashAndCashEquivalentsAtCarryingValue'],
            'cash flow': ['CashAndCashEquivalentsPeriodIncreaseDecrease'],
        }
        
        self.facts = self._extract_all_metrics()

    # ✅ FIX 1: safe file loading
    def _load_json(self):
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"XBRL file not found for {self.company_ticker}")

    def _extract_all_metrics(self):
        facts = []
        us_gaap = self.data.get("facts", {}).get("us-gaap", {})

        for metric_name, metric_data in us_gaap.items():
            if not metric_data:
                continue
                
            label = metric_data.get("label", metric_name)
            units = metric_data.get("units", {})

            for unit_type, entries in units.items():
                if unit_type != 'USD':
                    continue
                    
                for entry in entries:
                    if entry.get("form") != "10-K":
                        continue

                    year = entry.get("fy")

                    try:
                        year = int(year)
                    except:
                        continue

                    facts.append({
                        "metric": metric_name,
                        "label": label,
                        "value": entry.get("val"),
                        "unit": unit_type,
                        "year": year,
                        "filed": entry.get("filed", "")
                    })

        by_metric_year = {}
        for f in facts:
            key = (f["metric"], f["year"])
            if key not in by_metric_year:
                by_metric_year[key] = []
            by_metric_year[key].append(f)
        
        final = {}
        for (metric, year), metric_facts in by_metric_year.items():
            if metric_facts:
                if any('equity' in f['metric'].lower() for f in metric_facts):
                    final[(metric, year)] = max(metric_facts, key=lambda x: x.get("filed", ""))
                else:
                    final[(metric, year)] = max(metric_facts, key=lambda x: abs(x.get("value", 0) or 0))

        return list(final.values())

    def search(self, query: str):
        query = query.lower()
        
        year_range = self._parse_year_range(query)
        matching_metrics = self._find_matching_metrics(query)
        
        current_year = datetime.now().year
        MAX_ALLOWED_YEAR = current_year
        
        valid_facts = []
        for fact in self.facts:
            if fact["year"] > MAX_ALLOWED_YEAR:
                continue
                
            fact_matches_metric = False
            for metric_list in matching_metrics.values():
                if fact["metric"] in metric_list:
                    fact_matches_metric = True
                    break
            
            if not fact_matches_metric:
                continue
                
            if year_range:
                if not (year_range[0] <= fact["year"] <= year_range[1]):
                    continue
            
            valid_facts.append(fact)
        
        if not valid_facts:
            return []
        
        return self._rerank_results(valid_facts, query, year_range)
    
    # ✅ FIX 2: Added missing function (REQUIRED for explain_reranking)
    def search_with_scores(self, query: str):
        query = query.lower()
        
        year_range = self._parse_year_range(query)
        matching_metrics = self._find_matching_metrics(query)
        
        current_year = datetime.now().year
        MAX_ALLOWED_YEAR = current_year
        
        valid_facts = []
        for fact in self.facts:
            if fact["year"] > MAX_ALLOWED_YEAR:
                continue
                
            fact_matches_metric = False
            for metric_list in matching_metrics.values():
                if fact["metric"] in metric_list:
                    fact_matches_metric = True
                    break
            
            if not fact_matches_metric:
                continue
                
            if year_range:
                if not (year_range[0] <= fact["year"] <= year_range[1]):
                    continue
            
            valid_facts.append(fact)
        
        if not valid_facts:
            return []
        
        intent_weights = self._analyze_query_intent(query)
        
        scored_results = []
        
        for result in valid_facts:
            scores = {}
            
            scores['metric_relevance'] = self._score_metric_relevance(result, query)
            scores['recency'] = self._score_recency(result['year'], current_year, year_range)
            scores['value_significance'] = self._score_value_significance(result)
            scores['data_quality'] = self._score_data_quality(result)
            
            composite_score = sum(scores[c] * intent_weights[c] for c in scores)
            
            scored_results.append({
                'result': result,
                'scores': scores,
                'composite_score': composite_score
            })
        
        scored_results.sort(key=lambda x: x['composite_score'], reverse=True)
        
        return scored_results

    def _rerank_results(self, results, query, year_range=None):
        if not results:
            return results
        
        intent_weights = self._analyze_query_intent(query)
        
        scored_results = []
        current_year = datetime.now().year
        
        for result in results:
            scores = {}
            
            scores['metric_relevance'] = self._score_metric_relevance(result, query)
            scores['recency'] = self._score_recency(result['year'], current_year, year_range)
            scores['value_significance'] = self._score_value_significance(result)
            scores['data_quality'] = self._score_data_quality(result)
            
            composite_score = sum(scores[c] * intent_weights[c] for c in scores)
            
            scored_results.append({
                'result': result,
                'scores': scores,
                'composite_score': composite_score
            })
        
        scored_results.sort(key=lambda x: x['composite_score'], reverse=True)
        
        return [item['result'] for item in scored_results]

    def _analyze_query_intent(self, query):
        query_lower = query.lower()
        
        weights = {
            'metric_relevance': 0.4,
            'recency': 0.25,
            'value_significance': 0.2,
            'data_quality': 0.15
        }
        
        if self._parse_year_range(query):
            weights['recency'] = 0.15
            weights['metric_relevance'] = 0.5
        
        if any(word in query_lower for word in ['latest', 'current', 'recent', 'newest']):
            weights['recency'] = 0.4
            weights['metric_relevance'] = 0.35
        
        if any(word in query_lower for word in ['compare', 'vs', 'versus', 'comparison']):
            weights['value_significance'] = 0.3
            weights['recency'] = 0.2
        
        if any(word in query_lower for word in ['analysis', 'research']):
            weights['data_quality'] = 0.25
        
        if any(metric in query_lower for metric in ['profit', 'income', 'revenue']):
            weights['metric_relevance'] = 0.5
        
        total = sum(weights.values())
        return {k: v/total for k, v in weights.items()}

    def _score_metric_relevance(self, result, query):
        metric_name = result['metric'].lower()
        label = result.get('label', '').lower()
        
        query_terms = set(query.split())
        metric_words = set((metric_name + ' ' + label).split())
        
        exact_matches = len(query_terms.intersection(metric_words))
        if exact_matches > 0:
            return min(1.0, 0.8 + (exact_matches * 0.1))
        
        return 0.3

    def _score_recency(self, year, current_year, year_range=None):
        if year_range:
            span = year_range[1] - year_range[0]
            return 1.0 if span == 0 else 0.5
        
        years_old = current_year - year
        return max(0.2, 1.0 - (years_old * 0.1))

    def _score_value_significance(self, result):
        value = abs(result.get('value', 0) or 0)
        return 1.0 if value >= 1e11 else 0.5

    def _score_data_quality(self, result):
        return 0.7

    def _parse_year_range(self, query: str):
        import re
        
        match = re.search(r'(\d{4})-(\d{4})', query)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None

    def _find_matching_metrics(self, query: str):
        matching_metrics = {}
        for term, metrics in self.metric_mappings.items():
            if term in query:
                matching_metrics[term] = metrics
        
        if not matching_metrics:
            matching_metrics['revenue'] = self.metric_mappings['revenue']
        
        return matching_metrics

    def format_results(self, results):
        if not results:
            return "No matching data found."

        by_metric = {}
        for r in results:
            by_metric.setdefault(r['metric'], []).append(r)
        
        output = []
        for metric, metric_results in by_metric.items():
            output.append(f"{metric_results[0]['label']}:")
            
            for r in metric_results:
                val = r['value']
                if val and abs(val) >= 1e9:
                    val_formatted = f"${val/1e9:.1f}B"
                else:
                    val_formatted = f"${val:,.0f}" if val else "N/A"
                
                output.append(f"  - {val_formatted} ({r['year']})")
            
            output.append("")
        
        return "\n".join(output).rstrip()

    def explain_reranking(self, query: str, max_results=3):
        scored_results = self.search_with_scores(query)
        if not scored_results:
            return "No results to analyze."
        
        output = [f"RERANKING ANALYSIS for query: '{query}'"]
        
        for i, item in enumerate(scored_results[:max_results], 1):
            result = item['result']
            output.append(f"{i}. {result['label']} ({result['year']})")
        
        return "\n".join(output)

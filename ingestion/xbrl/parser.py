"""
XBRL Fact Parser.

Transforms raw SEC XBRL companyfacts JSON into normalized,
SQL-ready rows for structured financial analysis.

Key financial concepts are mapped to human-readable names
and organized by filing period for time-series analysis.
"""

import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Core financial concepts we extract and normalize.
# Maps us-gaap concept names to human-readable labels and categories.
CORE_CONCEPTS = {
    # Income Statement
    "Revenues": ("Revenue", "income_statement"),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("Revenue", "income_statement"),
    "SalesRevenueNet": ("Revenue", "income_statement"),
    "CostOfRevenue": ("Cost of Revenue", "income_statement"),
    "CostOfGoodsAndServicesSold": ("Cost of Revenue", "income_statement"),
    "GrossProfit": ("Gross Profit", "income_statement"),
    "OperatingIncomeLoss": ("Operating Income", "income_statement"),
    "OperatingExpenses": ("Operating Expenses", "income_statement"),
    "ResearchAndDevelopmentExpense": ("R&D Expense", "income_statement"),
    "SellingGeneralAndAdministrativeExpense": ("SG&A Expense", "income_statement"),
    "NetIncomeLoss": ("Net Income", "income_statement"),
    "EarningsPerShareBasic": ("EPS (Basic)", "income_statement"),
    "EarningsPerShareDiluted": ("EPS (Diluted)", "income_statement"),
    "IncomeTaxExpenseBenefit": ("Income Tax Expense", "income_statement"),
    "InterestExpense": ("Interest Expense", "income_statement"),
    # Balance Sheet
    "Assets": ("Total Assets", "balance_sheet"),
    "AssetsCurrent": ("Current Assets", "balance_sheet"),
    "CashAndCashEquivalentsAtCarryingValue": ("Cash & Equivalents", "balance_sheet"),
    "ShortTermInvestments": ("Short-Term Investments", "balance_sheet"),
    "AccountsReceivableNetCurrent": ("Accounts Receivable", "balance_sheet"),
    "InventoryNet": ("Inventory", "balance_sheet"),
    "PropertyPlantAndEquipmentNet": ("PP&E (Net)", "balance_sheet"),
    "Goodwill": ("Goodwill", "balance_sheet"),
    "IntangibleAssetsNetExcludingGoodwill": ("Intangible Assets", "balance_sheet"),
    "Liabilities": ("Total Liabilities", "balance_sheet"),
    "LiabilitiesCurrent": ("Current Liabilities", "balance_sheet"),
    "LongTermDebt": ("Long-Term Debt", "balance_sheet"),
    "LongTermDebtNoncurrent": ("Long-Term Debt", "balance_sheet"),
    "StockholdersEquity": ("Stockholders Equity", "balance_sheet"),
    "RetainedEarningsAccumulatedDeficit": ("Retained Earnings", "balance_sheet"),
    "CommonStockSharesOutstanding": ("Shares Outstanding", "balance_sheet"),
    # Cash Flow
    "NetCashProvidedByUsedInOperatingActivities": ("Operating Cash Flow", "cash_flow"),
    "NetCashProvidedByUsedInInvestingActivities": ("Investing Cash Flow", "cash_flow"),
    "NetCashProvidedByUsedInFinancingActivities": ("Financing Cash Flow", "cash_flow"),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("CapEx", "cash_flow"),
    "PaymentsOfDividends": ("Dividends Paid", "cash_flow"),
    "PaymentsForRepurchaseOfCommonStock": ("Share Buybacks", "cash_flow"),
    "DepreciationDepletionAndAmortization": ("D&A", "cash_flow"),
    # Key Ratios / Metrics
    "CommonStockDividendsPerShareDeclared": ("Dividends Per Share", "metrics"),
    "WeightedAverageNumberOfShareOutstandingBasic": ("Weighted Avg Shares (Basic)", "metrics"),
    "WeightedAverageNumberOfDilutedSharesOutstanding": ("Weighted Avg Shares (Diluted)", "metrics"),
}


@dataclass
class FinancialFact:
    """A single normalized financial fact ready for SQL storage."""
    cik: str
    entity_name: str
    taxonomy: str
    concept: str
    label: str
    category: str  # income_statement, balance_sheet, cash_flow, metrics
    value: float
    unit: str
    period_start: str  # YYYY-MM-DD or empty for instant
    period_end: str    # YYYY-MM-DD
    fiscal_year: int
    fiscal_quarter: Optional[int]  # None for annual
    filing_type: str   # 10-K or 10-Q
    filed_date: str
    accession_number: str
    is_annual: bool


class XBRLParser:
    """
    Parses raw XBRL companyfacts JSON into normalized FinancialFact rows.
    """

    def __init__(self, core_only: bool = True):
        """
        Args:
            core_only: If True, only extract CORE_CONCEPTS.
                       If False, extract all us-gaap concepts.
        """
        self.core_only = core_only

    def parse_company_facts(self, facts_json: Dict) -> List[FinancialFact]:
        """
        Parse the full companyfacts response into FinancialFact rows.

        Args:
            facts_json: Raw response from companyfacts API

        Returns:
            List of FinancialFact objects
        """
        cik = str(facts_json.get("cik", "")).zfill(10)
        entity_name = facts_json.get("entityName", "Unknown")
        all_facts = facts_json.get("facts", {})

        results = []

        for taxonomy, concepts in all_facts.items():
            if taxonomy not in ("us-gaap", "dei", "ifrs-full"):
                continue

            for concept_name, concept_data in concepts.items():
                # Filter to core concepts if requested
                if self.core_only and taxonomy == "us-gaap":
                    if concept_name not in CORE_CONCEPTS:
                        continue

                label_info = CORE_CONCEPTS.get(concept_name)
                if label_info:
                    label, category = label_info
                else:
                    label = concept_data.get("label", concept_name)
                    category = "other"

                units = concept_data.get("units", {})
                for unit_name, fact_array in units.items():
                    for fact in fact_array:
                        parsed = self._parse_single_fact(
                            fact, cik, entity_name, taxonomy,
                            concept_name, label, category, unit_name
                        )
                        if parsed:
                            results.append(parsed)

        # Deduplicate: keep the most recent filing for each
        # (concept, period_end, fiscal_year) combination
        results = self._deduplicate(results)

        logger.info(
            f"Parsed {len(results)} facts for {entity_name} (CIK {cik})"
        )
        return results

    def _parse_single_fact(
        self, fact: Dict, cik: str, entity_name: str,
        taxonomy: str, concept: str, label: str,
        category: str, unit: str
    ) -> Optional[FinancialFact]:
        """Parse a single XBRL fact entry."""
        val = fact.get("val")
        if val is None:
            return None

        try:
            value = float(val)
        except (ValueError, TypeError):
            return None

        end_date = fact.get("end", "")
        start_date = fact.get("start", "")
        filed = fact.get("filed", "")
        accn = fact.get("accn", "")
        form = fact.get("form", "")
        fy = fact.get("fy", 0)
        fp = fact.get("fp", "")

        # Only keep 10-K and 10-Q filings
        if form not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
            return None

        is_annual = form in ("10-K", "10-K/A")

        # Determine fiscal quarter
        fiscal_quarter = None
        if fp and fp.startswith("Q"):
            try:
                fiscal_quarter = int(fp[1:])
            except ValueError:
                pass
        elif fp == "FY":
            fiscal_quarter = None  # annual

        # Derive the actual data year from period_end, not the filing's fy.
        # The fy field represents the filing year, but a 10-K often includes
        # comparative data from prior years. The period_end tells us which
        # year the data actually belongs to.
        data_year = fy or 0
        if end_date and len(end_date) >= 4:
            try:
                data_year = int(end_date[:4])
            except ValueError:
                pass

        # For annual facts, determine if this is truly annual data by
        # checking the duration (period_start to period_end).
        # Annual data spans ~330-400 days; quarterly spans ~80-100 days.
        actual_is_annual = is_annual
        if start_date and end_date:
            try:
                from datetime import datetime
                d_start = datetime.strptime(start_date, "%Y-%m-%d")
                d_end = datetime.strptime(end_date, "%Y-%m-%d")
                duration = (d_end - d_start).days
                if duration > 300:
                    actual_is_annual = True
                    fiscal_quarter = None
                elif duration < 120:
                    actual_is_annual = False
                    # Estimate quarter from end month
                    if fiscal_quarter is None:
                        month = d_end.month
                        fiscal_quarter = (month - 1) // 3 + 1
            except (ValueError, TypeError):
                pass

        return FinancialFact(
            cik=cik,
            entity_name=entity_name,
            taxonomy=taxonomy,
            concept=concept,
            label=label,
            category=category,
            value=value,
            unit=unit,
            period_start=start_date,
            period_end=end_date,
            fiscal_year=data_year,
            fiscal_quarter=fiscal_quarter,
            filing_type=form,
            filed_date=filed,
            accession_number=accn,
            is_annual=actual_is_annual,
        )

    def _deduplicate(self, facts: List[FinancialFact]) -> List[FinancialFact]:
        """
        Deduplicate facts at two levels:
        1. Same concept + same period → keep most recently filed
        2. Same label + same period → keep the preferred concept
           (handles cases where a company switches XBRL tags over time,
            e.g., Revenues → RevenueFromContractWithCustomerExcludingAssessedTax)
        """
        # Level 1: dedup by raw concept + period
        by_concept = {}
        for f in facts:
            key = (f.cik, f.concept, f.period_start, f.period_end)
            existing = by_concept.get(key)
            if existing is None or f.filed_date > existing.filed_date:
                by_concept[key] = f

        # Level 2: dedup by label + period (keep most recently filed)
        by_label = {}
        for f in by_concept.values():
            key = (f.cik, f.label, f.category, f.period_start, f.period_end)
            existing = by_label.get(key)
            if existing is None or f.filed_date > existing.filed_date:
                by_label[key] = f

        return list(by_label.values())

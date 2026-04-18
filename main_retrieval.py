from retrieval.xbrl_retriever import XBRLRetriever
import re


def parse_query(query):
    """Parse query to extract companies and search terms with fuzzy matching"""
    import difflib
    import os
    
    # Common company name mappings
    company_mappings = {
        'apple': 'AAPL', 'aapl': 'AAPL',
        'tesla': 'TSLA', 'tsla': 'TSLA',
        'microsoft': 'MSFT', 'msft': 'MSFT',
        'nvidia': 'NVDA', 'nvda': 'NVDA',
        'amazon': 'AMZN', 'amzn': 'AMZN',
        'meta': 'META', 'facebook': 'META',
        'google': 'GOOGL', 'alphabet': 'GOOGL',
        'salesforce': 'CRM', 'crm': 'CRM',
        'snowflake': 'SNOW', 'snow': 'SNOW',
        'crowdstrike': 'CRWD', 'crwd': 'CRWD',
        'palo alto': 'PANW', 'panw': 'PANW',
        'fortinet': 'FTNT', 'ftnt': 'FTNT'
    }
    
    # Check which companies actually have data
    available_companies = set()
    data_dir = "output/xbrl/raw"
    if os.path.exists(data_dir):
        available_companies = {f for f in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, f))}
    
    # Extract company tickers and names from query
    companies = set()
    remaining_query = query
    found_companies = []
    
    # First pass: exact matches
    for name, ticker in company_mappings.items():
        if name.lower() in query.lower() or ticker.lower() in query.lower():
            if ticker in available_companies:
                companies.add(ticker)
                found_companies.append(name)
                found_companies.append(ticker)
    
    # Second pass: fuzzy matching for typos (if no exact matches found)
    if not companies:
        all_company_names = list(company_mappings.keys()) + list(company_mappings.values())
        words = re.findall(r'\b\w+\b', query.lower())
        
        for word in words:
            # Find close matches
            matches = difflib.get_close_matches(word, all_company_names, n=1, cutoff=0.8)
            if matches:
                match = matches[0]
                ticker = company_mappings.get(match, match.upper())
                if ticker in available_companies:
                    companies.add(ticker)
                    found_companies.append(match)
    
    # Remove found companies from query
    for company in found_companies:
        remaining_query = re.sub(r'\b' + re.escape(company) + r'\b', '', remaining_query, flags=re.IGNORECASE)
    
    # Remove any remaining words that could be company tickers (2-5 letter uppercase words)
    words = remaining_query.split()
    cleaned_words = []
    for word in words:
        # Keep words that are clearly years, metrics, or range indicators
        if word.isdigit() and len(word) == 4:  # Years like 2023, 2024
            cleaned_words.append(word)
        elif word.lower() in ['revenue', 'sales', 'income', 'profit', 'earnings', 'cash', 'flow', 'assets', 
                             'liabilities', 'equity', 'net', 'operating', 'stockholders', 'and', 'to']:
            cleaned_words.append(word)
        elif '-' in word and len(word) == 9 and word.replace('-', '').isdigit():  # Year ranges like 2022-2024
            cleaned_words.append(word)
        elif len(word) < 2 or len(word) > 5:  # Keep longer words (likely not tickers)
            cleaned_words.append(word)
        elif not word.isupper():  # Keep mixed case words
            cleaned_words.append(word)
        # Remove short uppercase words (likely tickers) that aren't in our valid list
    
    remaining_query = ' '.join(cleaned_words)
    
    # Clean up remaining query - be more selective about what to remove
    remaining_query = re.sub(r'\bvs\b|\bversus\b|\bfor\b|\bthe\b|\bof\b|\bin\b', '', remaining_query, flags=re.IGNORECASE)
    # Keep "to" for year ranges, keep "and" for multi-metric queries
    remaining_query = re.sub(r'[^\w\s-]', '', remaining_query)  # Remove punctuation but keep dashes
    remaining_query = ' '.join(remaining_query.split())
    
    # Default to revenue if no specific metric found
    if not remaining_query or remaining_query.isdigit():
        remaining_query = 'revenue'
    
    return list(companies), remaining_query.strip()


def main():
    print("XBRL Financial Data Retrieval System")
    print("Supports queries like: 'Apple vs Tesla revenue 2024' or 'AAPL MSFT profit 2022-2024'")
    print("Available metrics: revenue, profit, income, assets, liabilities, equity, cash, etc.")
    print("Features: Intelligent reranking, year ranges, multi-company queries")
    print("=" * 75)
    
    while True:
        query = input("\nEnter query: ").strip()

        if not query:
            continue

        # Special commands
        if query.lower() in ['help']:
            print("\n" + "="*60)
            print("HELP - XBRL Financial Data Retrieval System")
            print("="*60)
            print("Query Examples:")
            print("  'Apple revenue 2024'           - Single company, specific year")
            print("  'AAPL TSLA profit 2022-2024'    - Multiple companies, year range")
            print("  'Tesla vs Nvidia assets'        - Compare companies")
            print("  'Microsoft cash 2023'           - Specific metric")
            print()
            print("Available Metrics:")
            print("  revenue, profit, income, assets, liabilities, equity, cash")
            print("  And 400+ other XBRL financial metrics...")
            print()
            print("Special Commands:")
            print("  'explain' or 'analyze'          - Show reranking analysis for last query")
            print("  'help'                          - Show this help")
            print("  'quit' or 'exit'                - Exit the system")
            print("="*60)
            continue
        
        elif query.lower() in ['explain', 'analyze', 'reranking']:
            if 'last_query' in locals() and 'last_companies' in locals():
                print(f"\n🔍 RERANKING ANALYSIS for '{last_query}'")
                print("="*60)
                # Show analysis for first company as example
                if last_companies:
                    retriever = XBRLRetriever(last_companies[0])
                    analysis = retriever.explain_reranking(last_query, max_results=5)
                    print(analysis)
            else:
                print("No previous query to analyze. Try a query first, then type 'explain'.")
            continue
        
        if query.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break

        # Parse companies and search terms from query
        companies, search_query = parse_query(query)
        
        if not companies:
            print("No companies found in query. Please include company names or tickers.")
            continue
        
        if not search_query:
            search_query = "revenue"  # Default to revenue if no specific metric requested
        
        # Query each company
        all_results = []
        missing_companies = []
        for company in companies:
            try:
                retriever = XBRLRetriever(company)
                results = retriever.search(search_query)
                if results:
                    all_results.append((company, results))
                else:
                    missing_companies.append(f"{company} (no data found)")
            except FileNotFoundError:
                missing_companies.append(f"{company} (data not available)")
            except Exception as e:
                missing_companies.append(f"{company} (error: {str(e)[:50]})")
        
        # Display results
        if all_results:
            print(f"\nResults for '{search_query}':\n")
            for company, results in all_results:
                print(f"{company}:")
                formatted = XBRLRetriever(company).format_results(results)
                print(formatted)
                
                # Show reranking explanation for multi-result queries
                if len(results) > 1:
                    print("💡 Results intelligently ranked by relevance, recency, and data quality")
                print()
            
            # Store last query for analysis
            last_query = search_query
            last_companies = companies
        
        if missing_companies:
            print("Companies with issues:")
            for msg in missing_companies:
                print(f"  - {msg}")
            print()


if __name__ == "__main__":
    main()

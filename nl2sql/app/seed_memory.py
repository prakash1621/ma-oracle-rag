import asyncio

from vanna.capabilities.agent_memory import ToolMemory, AgentMemory

from nl2sql.app.config import get_settings
from nl2sql.app.database import DatabaseClient
from nl2sql.app.memory import build_tool_context, count_memories, create_agent_memory
from nl2sql.app.schema import load_database_schema
from nl2sql.app.security import SQLValidator


TRAINING_EXAMPLES = [
    ToolMemory(
        question="Show me the top 5 companies by total assets",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS total_assets
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE f.concept = 'Assets'
              AND f.is_annual = 1
              AND f.period_end = (SELECT MAX(period_end) FROM financial_facts WHERE concept = 'Assets')
            ORDER BY total_assets DESC
            LIMIT 5
            """
        },
    ),
    ToolMemory(
        question="How many companies are in the database?",
        tool_name="run_sql",
        args={"sql": "SELECT COUNT(*) AS total_companies FROM companies"},
    ),
    ToolMemory(
        question="List all companies and their ticker symbols",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT entity_name, ticker
            FROM companies
            ORDER BY entity_name
            """
        },
    ),
    ToolMemory(
        question="Show the latest filing date for each company",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, MAX(f.filed_date) AS latest_filed_date
            FROM companies c
            JOIN financial_facts f ON c.cik = f.cik
            GROUP BY c.cik, c.entity_name, c.ticker
            ORDER BY latest_filed_date DESC
            """
        },
    ),
    ToolMemory(
        question="What are the most common filing types in the financial facts table?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT filing_type, COUNT(*) AS filing_count
            FROM financial_facts
            GROUP BY filing_type
            ORDER BY filing_count DESC
            """
        },
    ),
    ToolMemory(
        question="Show the top 10 most common financial concepts",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT concept, COUNT(*) AS concept_count
            FROM financial_facts
            GROUP BY concept
            ORDER BY concept_count DESC
            LIMIT 10
            """
        },
    ),
    ToolMemory(
        question="What is Apple's total assets for fiscal year 2024?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.value AS total_assets, f.unit, f.period_end
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'AAPL'
              AND f.concept = 'Assets'
              AND f.fiscal_year = 2024
              AND f.is_annual = 1
            ORDER BY f.period_end DESC
            LIMIT 1
            """
        },
    ),
    ToolMemory(
        question="Show Microsoft's annual net income over the last 5 fiscal years",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.fiscal_year, f.value AS net_income, f.unit
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'MSFT'
              AND f.concept = 'NetIncomeLoss'
              AND f.is_annual = 1
            ORDER BY f.fiscal_year DESC
            LIMIT 5
            """
        },
    ),
    ToolMemory(
        question="Which company had the highest annual gross profit in 2024?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS gross_profit
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE f.concept = 'GrossProfit'
              AND f.fiscal_year = 2024
              AND f.is_annual = 1
            ORDER BY gross_profit DESC
            LIMIT 1
            """
        },
    ),
    ToolMemory(
        question="Show the latest cash and cash equivalents for each company",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS cash_and_equivalents, f.period_end
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE f.concept = 'CashAndCashEquivalentsAtCarryingValue'
              AND f.period_end = (
                  SELECT MAX(f2.period_end)
                  FROM financial_facts f2
                  WHERE f2.cik = f.cik
                    AND f2.concept = 'CashAndCashEquivalentsAtCarryingValue'
              )
            ORDER BY cash_and_equivalents DESC
            """
        },
    ),
    ToolMemory(
        question="Show NVIDIA's latest balance sheet items",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.label, f.value, f.unit, f.period_end
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'NVDA'
              AND f.category = 'balance_sheet'
              AND f.period_end = (
                  SELECT MAX(f2.period_end)
                  FROM financial_facts f2
                  WHERE f2.cik = f.cik
                    AND f2.category = 'balance_sheet'
              )
            ORDER BY f.label
            """
        },
    ),
    ToolMemory(
        question="Get Meta's diluted EPS by quarter for fiscal year 2025",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.fiscal_quarter, f.value AS diluted_eps
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'META'
              AND f.concept = 'EarningsPerShareDiluted'
              AND f.fiscal_year = 2025
            ORDER BY f.fiscal_quarter
            """
        },
    ),
    ToolMemory(
        question="Compare accounts receivable for Amazon and Alphabet in fiscal year 2025 quarter 1",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS accounts_receivable
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker IN ('AMZN', 'GOOGL')
              AND f.concept = 'AccountsReceivableNetCurrent'
              AND f.fiscal_year = 2025
              AND f.fiscal_quarter = 1
            ORDER BY c.ticker
            """
        },
    ),
    ToolMemory(
        question="Show Apple's dividend per share declared in fiscal year 2025",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.period_start, f.period_end, f.value AS dividend_per_share
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'AAPL'
              AND f.concept = 'CommonStockDividendsPerShareDeclared'
              AND f.fiscal_year = 2025
            ORDER BY f.period_end
            """
        },
    ),
    ToolMemory(
        question="Show Tesla's current assets and total assets for fiscal year 2025 quarter 3",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.concept, f.label, f.value, f.unit
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'TSLA'
              AND f.concept IN ('AssetsCurrent', 'Assets')
              AND f.fiscal_year = 2025
              AND f.fiscal_quarter = 3
            ORDER BY f.concept
            """
        },
    ),
    ToolMemory(
        question="Find annual interest expense for all companies in fiscal year 2024",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS interest_expense
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE f.concept = 'InterestExpense'
              AND f.fiscal_year = 2024
              AND f.is_annual = 1
            ORDER BY interest_expense DESC
            """
        },
    ),
    ToolMemory(
        question="Show goodwill values for Palo Alto Networks and Fortinet",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, f.value AS goodwill, f.period_end
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker IN ('PANW', 'FTNT')
              AND f.concept = 'Goodwill'
            ORDER BY c.ticker, f.period_end DESC
            """
        },
    ),
    ToolMemory(
        question="Which companies have the most balance sheet rows in the database?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT c.entity_name, c.ticker, COUNT(*) AS balance_sheet_rows
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE f.category = 'balance_sheet'
            GROUP BY c.cik, c.entity_name, c.ticker
            ORDER BY balance_sheet_rows DESC
            """
        },
    ),
    ToolMemory(
        question="What was Apple's total revenue in fiscal year 2009?",
        tool_name="run_sql",
        args={
            "sql": """
            SELECT f.value AS total_revenue, f.unit, f.period_end
            FROM financial_facts f
            JOIN companies c ON c.cik = f.cik
            WHERE c.ticker = 'AAPL'
              AND f.concept IN ('Revenues', 'SalesRevenueNet', 'RevenueFromContractWithCustomerExcludingAssessedTax')
              AND f.fiscal_year = 2009
              AND f.is_annual = 1
            ORDER BY f.period_end DESC
            LIMIT 1
            """
        },
    ),
]


async def seed_agent_memory(agent_memory: AgentMemory) -> None:
    context = build_tool_context(agent_memory)
    existing_questions = {memory.question for memory in await agent_memory.get_recent_memories(context, limit=5000)}

    for example in TRAINING_EXAMPLES:
        if example.question in existing_questions:
            continue
        await agent_memory.save_tool_usage(
            question=example.question,
            tool_name=example.tool_name,
            args=example.args,
            context=context,
            success=True,
        )


async def validate_examples() -> None:
    settings = get_settings()
    database = DatabaseClient(settings.db_path)
    schema = load_database_schema(settings.db_path)
    validator = SQLValidator(schema=schema, database=database)
    agent_memory = create_agent_memory(settings)

    for example in TRAINING_EXAMPLES:
        sql = example.args["sql"]
        validator.validate(sql)

    await seed_agent_memory(agent_memory)
    print(f"Validated and loaded {count_memories(agent_memory)} training examples into memory.")
    print("These examples are loaded automatically when the API starts.")


if __name__ == "__main__":
    asyncio.run(validate_examples())

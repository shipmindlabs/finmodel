"""The worked examples the golden tests compute: three statements and their checks."""

import pytest

from finmodel import (
    Block,
    Carry,
    Check,
    Checklist,
    ComputedLine,
    InputLine,
    PeriodicModel,
    Rounding,
    Statement,
)


def saas_pnl() -> Statement:
    return Statement(
        id="pnl",
        label="Profit and loss",
        rounding=Rounding(2),
        children=[
            Block(
                id="revenue",
                label="Revenue",
                children=[
                    InputLine(id="subscriptions", label="Subscriptions"),
                    InputLine(id="services", label="Professional services"),
                    ComputedLine(
                        id="total_revenue",
                        label="Total revenue",
                        formula="subscriptions + services",
                    ),
                ],
            ),
            Block(
                id="cost_of_revenue",
                label="Cost of revenue",
                children=[
                    InputLine(id="hosting", label="Hosting"),
                    InputLine(id="support", label="Customer support"),
                    ComputedLine(
                        id="total_cost_of_revenue",
                        label="Total cost of revenue",
                        formula="hosting + support",
                    ),
                ],
            ),
            ComputedLine(
                id="gross_profit",
                label="Gross profit",
                formula="total_revenue - total_cost_of_revenue",
            ),
            ComputedLine(
                id="gross_margin",
                label="Gross margin",
                formula="gross_profit / total_revenue",
                rounding=Rounding(4),
            ),
            Block(
                id="operating_expenses",
                label="Operating expenses",
                children=[
                    InputLine(id="sales_and_marketing", label="Sales and marketing"),
                    InputLine(
                        id="research_and_development",
                        label="Research and development",
                    ),
                    InputLine(
                        id="general_and_administrative",
                        label="General and administrative",
                    ),
                    ComputedLine(
                        id="total_operating_expenses",
                        label="Total operating expenses",
                        formula=(
                            "sales_and_marketing + research_and_development"
                            " + general_and_administrative"
                        ),
                    ),
                ],
            ),
            ComputedLine(
                id="operating_income",
                label="Operating income",
                formula="gross_profit - total_operating_expenses",
            ),
            ComputedLine(
                id="operating_margin",
                label="Operating margin",
                formula="operating_income / total_revenue",
                rounding=Rounding(4),
            ),
        ],
    )


def cash_flow() -> PeriodicModel:
    return PeriodicModel(
        Statement(
            id="cash_flow",
            label="Cash flow",
            rounding=Rounding(2),
            children=[
                InputLine(id="opening_cash", label="Opening cash"),
                InputLine(id="receipts", label="Receipts from customers"),
                InputLine(id="payments", label="Payments to suppliers and staff"),
                ComputedLine(
                    id="net_cash_flow",
                    label="Net cash flow",
                    formula="receipts - payments",
                ),
                ComputedLine(
                    id="closing_cash",
                    label="Closing cash",
                    formula="opening_cash + net_cash_flow",
                ),
            ],
        ),
        carries=[
            Carry(
                opening="opening_cash",
                closing="closing_cash",
                movement="net_cash_flow",
            )
        ],
    )


def balance_sheet() -> Statement:
    return Statement(
        id="balance_sheet",
        label="Balance sheet",
        rounding=Rounding(2),
        children=[
            Block(
                id="current_assets",
                label="Current assets",
                children=[
                    InputLine(id="cash", label="Cash"),
                    InputLine(id="receivables", label="Trade receivables"),
                    InputLine(id="inventory", label="Inventory"),
                    ComputedLine(
                        id="total_current_assets",
                        label="Total current assets",
                        formula="cash + receivables + inventory",
                    ),
                ],
            ),
            Block(
                id="fixed_assets",
                label="Fixed assets",
                children=[
                    InputLine(id="equipment", label="Equipment at cost"),
                    InputLine(
                        id="accumulated_depreciation",
                        label="Accumulated depreciation",
                    ),
                    ComputedLine(
                        id="net_fixed_assets",
                        label="Net fixed assets",
                        formula="equipment + accumulated_depreciation",
                    ),
                ],
            ),
            ComputedLine(
                id="total_assets",
                label="Total assets",
                formula="total_current_assets + net_fixed_assets",
            ),
            Block(
                id="liabilities",
                label="Liabilities",
                children=[
                    InputLine(id="payables", label="Trade payables"),
                    InputLine(id="deferred_revenue", label="Deferred revenue"),
                    ComputedLine(
                        id="total_liabilities",
                        label="Total liabilities",
                        formula="payables + deferred_revenue",
                    ),
                ],
            ),
            Block(
                id="equity",
                label="Equity",
                children=[
                    InputLine(id="share_capital", label="Share capital"),
                    InputLine(id="retained_earnings", label="Retained earnings"),
                    ComputedLine(
                        id="total_equity",
                        label="Total equity",
                        formula="share_capital + retained_earnings",
                    ),
                ],
            ),
            ComputedLine(
                id="total_liabilities_and_equity",
                label="Total liabilities and equity",
                formula="total_liabilities + total_equity",
            ),
        ],
    )


@pytest.fixture
def pnl_statement() -> Statement:
    return saas_pnl()


@pytest.fixture
def cash_flow_model() -> PeriodicModel:
    return cash_flow()


@pytest.fixture
def balance_sheet_statement() -> Statement:
    return balance_sheet()


@pytest.fixture
def balance_sheet_books(balance_sheet_statement: Statement) -> Checklist:
    return Checklist(
        balance_sheet_statement,
        [
            Check.balances(
                assets="total_assets",
                liabilities="total_liabilities",
                equity="total_equity",
            ),
            Check(
                id="funding_adds_up",
                label="Assets equal the funding side",
                left="total_assets",
                right="total_liabilities_and_equity",
            ),
        ],
    )

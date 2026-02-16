import pytest
from src.parser import BankParser
import os

@pytest.fixture
def parser():
    # Use real config for testing parsers
    return BankParser("data/banks_config.json")

def test_parse_hsbc_synthetic(parser):
    """Verify HSBC synthetic CSV parsing."""
    file_path = "tests/input_data/synthetic_hsbc.csv"
    assert os.path.exists(file_path)
    
    txs = parser.parse("HSBC", file_path)
    assert len(txs) == 10
    
    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx
        assert tx["type"] in ["income", "expense"]
        # HSBC negate_amounts is True in config, and type_determination is amount_sign.
        # If amount in CSV is -50.0, float(-50.0) = -50.0. negate_amounts makes it 50.0.
        # But wait, type_determination 'amount_sign' uses raw_amount (before negation).
        # raw_amount -50.0 -> expense. raw_amount 50.0 -> income.
        
def test_parse_wise_synthetic(parser):
    """Verify Wise synthetic CSV parsing."""
    file_path = "tests/input_data/synthetic_wise.csv"
    assert os.path.exists(file_path)
    
    txs = parser.parse("Wise", file_path)
    assert len(txs) == 10
    
    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx
        assert tx["type"] in ["income", "expense"]
        # Wise uses direction_column.


import logging
import pandas as pd
from datetime import datetime
from config.settings import (
    MAX_DAILY_TRADES,
    MAX_POSITION_SIZE,
    DEFAULT_POSITION_SIZE,
    MIN_RISK_REWARD_RATIO
)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_risk_configuration():
    logger.info("🧪 Testing Risk Management Config...")
    
    # 1. Test Limits
    logger.info(f"Max Daily Trades: {MAX_DAILY_TRADES}")
    assert MAX_DAILY_TRADES == 5, f"Expected 5, got {MAX_DAILY_TRADES}"
    
    logger.info(f"Max Position Size: {MAX_POSITION_SIZE}")
    assert MAX_POSITION_SIZE == 0.1, f"Expected 0.1, got {MAX_POSITION_SIZE}"
    
    logger.info(f"Default Position Size: {DEFAULT_POSITION_SIZE}")
    assert DEFAULT_POSITION_SIZE == 0.01, f"Expected 0.01, got {DEFAULT_POSITION_SIZE}"
    
    logger.info(f"Min R:R: {MIN_RISK_REWARD_RATIO}")
    assert MIN_RISK_REWARD_RATIO == 1.5, f"Expected 1.5, got {MIN_RISK_REWARD_RATIO}"
    
    logger.info("✅ Risk Configuration Verified")

def calculate_position_size(account_balance, risk_pct, sl_pips):
    """
    Calculate position size in lots.
    Risk = Balance * RiskPct
    Value per pip per lot (for EURUSD) = $10
    Risk = Lots * Pips * $10
    Lots = Risk / (Pips * 10)
    """
    risk_amount = account_balance * risk_pct
    pip_value_per_lot = 10.0 # Standard lot EURUSD
    
    lots = risk_amount / (sl_pips * pip_value_per_lot)
    return round(lots, 2)

def test_position_sizing_logic():
    logger.info("🧪 Testing Position Sizing Logic...")
    
    account_balance = 10000
    risk_pct = 0.01 # 1% risk
    sl_pips = 10
    
    # Risk = $100
    # SL = 10 pips
    # Value per pip should be $10
    # Standard lot: 1 pip = $10
    # So we need 1.0 lot? 
    # Wait, $100 risk / (10 pips * $10/pip/lot) = 1 lot.
    
    lots = calculate_position_size(account_balance, risk_pct, sl_pips)
    logger.info(f"Balance: ${account_balance} | Risk: {risk_pct*100}% | SL: {sl_pips} pips")
    logger.info(f"Calculated Lots: {lots}")
    
    # Validating against manual calc
    risk_amount = account_balance * risk_pct
    assert lots == 1.0, f"Expected 1.0 lot, got {lots}"
    
    # Test Micro Account case
    # Balance $1000, 1% risk = $10
    # SL 20 pips
    # Lots = 10 / (20 * 10) = 10 / 200 = 0.05 lots
    lots_micro = calculate_position_size(1000, 0.01, 20)
    logger.info(f"Micro Account Checks: {lots_micro} lots")
    assert lots_micro == 0.05, f"Expected 0.05 lot, got {lots_micro}"
    
    logger.info("✅ Position Sizing Logic Verified")

if __name__ == "__main__":
    test_risk_configuration()
    test_position_sizing_logic()

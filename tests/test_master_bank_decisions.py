from copy import deepcopy
import json

import pytest

from bot.master_comparison import freeze_bank_research_decisions
from test_p3_asof_real_decoder_integration import _selected_case


def test_actual_engines_abstain_on_bank_only_without_fabricating_usd_or_pnl():
    selection,*_=_selected_case()
    before=deepcopy(selection)
    result=freeze_bank_research_decisions(selection,decision_at_ms=17000)
    assert result['paired_admission_decisions']==1
    assert result['pairs'][0]['reference']['action']=='WAIT'
    assert result['pairs'][0]['master']['action']=='WAIT'
    assert 'features_unknown' in result['pairs'][0]['master']['reasons']
    assert result['reference_entries']==result['master_entries']==0
    assert result['net_market_pnl_lamports'] is None
    assert not result['strategy_performance_comparable']
    assert selection==before
    json.dumps(result,allow_nan=False)
    assert freeze_bank_research_decisions(selection,decision_at_ms=17000)==result


def test_future_bank_and_changed_decision_cannot_be_frozen():
    selection,*_=_selected_case()
    with pytest.raises(ValueError):
        freeze_bank_research_decisions(selection,decision_at_ms=16999)
    selection['original_strict_selection']['records'][0]['source_row']['snapshot_available_at_ms']=17001
    with pytest.raises(ValueError):
        freeze_bank_research_decisions(selection,decision_at_ms=17000)

"""A failed first read retains a useful cause without retaining exception text."""
import asyncio
import json

import pytest

from bot.p3 import campaign,collect
from test_p3_collection import Transport
from test_p3_quotes import Response


@pytest.mark.parametrize('kind',['discovery','rpc'])
def test_transport_receipt_retains_error_class_and_one_attempt_without_sensitive_text(kind):
    error=OSError('api_key=synthetic-must-not-be-retained')
    response=Response(error=error)
    transport=Transport(gets=[response] if kind=='discovery' else [],posts=[response] if kind=='rpc' else [])
    events=[]
    def append(name,**record):events.append(dict(kind=name,**record))
    if kind=='discovery':
        session=campaign.CampaignSession(transport,1)
        asyncio.run(campaign._discover(session,append))
    else:
        session=collect.ReadOnlySession(transport,1)
        asyncio.run(collect._rpc(session,append,'getSlot',[]))
    assert len(events)==len(transport.calls)==session.requests_used==1
    assert events[0]['reason']=='transport_or_timeout'
    assert events[0]['payload']['transport_error_type']=='OSError'
    assert 'synthetic-must-not-be-retained' not in json.dumps(events)

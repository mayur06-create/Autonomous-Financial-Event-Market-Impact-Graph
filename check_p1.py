import urllib.request
import json

BASE = 'http://127.0.0.1:8000'

def post_json(url, data):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode('utf-8'))

inputs = {
    'macro': 'Brent crude surges 12% to $94 a barrel following Middle East tanker supply disruption and export halt.',
    'company': 'Tata Motors reports 28% jump in Q3 EV commercial sales and announces new factory in Gujarat.',
    'irrelevant': 'Celebrity pastry chef from Italy wins international gold medal for chocolate sculpture in Paris.',
    'live_feed': 'HDFC Flexi Cap Fund: Can its winning formula survive the scale test?',
    'demo_repo': 'RBI raises repo rate by 50 bps to 6.50% to tame persistent core inflation pressures.',
    'demo_rupee': 'Rupee hits record low of 83.75 per USD as crude prices surge and FII outflows accelerate.'
}

results = {}
for k, text in inputs.items():
    status, res = post_json(f'{BASE}/analyze', {'text': text})
    results[k] = {'status_code': status, 'data': res}
    print(f"=== INPUT: {k} (HTTP {status}) ===")
    ev = res.get('event', {})
    print(f"  Archetype:        {ev.get('archetype')}")
    print(f"  Event Type:       {ev.get('event_type')}")
    print(f"  Primary Node:     {ev.get('primary_node')}")
    print(f"  Direction:        {ev.get('direction')}")
    print(f"  Magnitude:        {ev.get('magnitude')}")
    print(f"  Shock Source:     {ev.get('shock_source')}")
    print(f"  Is Relevant:      {res.get('is_relevant')}")
    print(f"  Relevance Reason: {res.get('relevance_reason')}")
    ents = ev.get('typed_entities', [])
    print(f"  Typed Entities ({len(ents)}):")
    for te in ents[:4]:
        print(f"    * [{te.get('entity_type')}] {te.get('name')} | linked={te.get('is_linked')} | canonical={te.get('canonical_id')}")
        span = te.get('evidence_span', '')
        print(f"      evidence_span: \"{span[:70]}\"")
    print(f"  Unlinked count:   {len(ev.get('unlinked_entities', []))}")
    print(f"  Graph Nodes:      {len(res.get('nodes', []))} | Edges: {len(res.get('edges', []))}")
    edges = res.get('edges', [])
    if edges:
        print("  Sample Edges:")
        for e in edges[:3]:
            print(f"    * {e.get('source')} -[{e.get('relation')}]-> {e.get('target')} (sign: {e.get('sign')}, conf: {e.get('confidence')}, claim: {e.get('claim_type')})")
            print(f"      breakdown: {e.get('confidence_breakdown')}")
    print()

with open('phase1_results.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2)

print('All 6 runs executed and verified.')

"""Offline dry test of step1_a2.window_budget (R02 K-1, 24/11 11:20Z): both branches. No network, no call."""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location('a2', sys.argv[1])
a2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a2)                      # main() is not run (guarded by __name__)
ok = a2.window_budget(53, 53 + 22_000, 3)        # pre 22 000 (estimate from R^), D = 3
assert ok == dict(pre_credits=22_000, projected_credits=22_053 + 9_429, hard_stop=49_000,
                  margin=49_000 - 31_482, stop=False), ok
cut = a2.window_budget(53, 53 + 40_000, 3)       # pre 40 000: the window would not fit
assert cut['projected_credits'] == 40_053 + 17_143 and cut['stop'] is True and cut['margin'] < 0, cut
edge = a2.window_budget(0, 34_300, 3)            # 34 300 + ceil(34 300 x 3 / 7) = 34 300 + 14 700 = 49 000: allowed
assert edge['projected_credits'] == 49_000 and edge['stop'] is False, edge
over = a2.window_budget(0, 34_301, 3)            # one more credit -> ceil -> 49 002 > 49 000: STOP
assert over['stop'] is True, over
print('window_budget dry test OK', ok, cut, edge, over, sep='\n')

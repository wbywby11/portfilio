# -*- coding: utf-8 -*-
import os

pairs = [
    ('d:/project/portfilio/options_pricing/risk.py', 'd:/project/portfilio/portfilio-end/app/options/risk.py'),
    ('d:/project/portfilio/options_pricing/vol/iv_calculator.py', 'd:/project/portfilio/portfilio-end/app/options/vol/iv_calculator.py'),
    ('d:/project/portfilio/options_pricing/vol/surface.py', 'd:/project/portfilio/portfilio-end/app/options/vol/surface.py'),
    ('d:/project/portfilio/options_pricing/config.py', 'd:/project/portfilio/portfilio-end/app/options/config.py'),
    ('d:/project/portfilio/options_pricing/data_loader.py', 'd:/project/portfilio/portfilio-end/app/options/data_loader.py'),
    ('d:/project/portfilio/options_pricing/product_manager.py', 'd:/project/portfilio/portfilio-end/app/options/product_manager.py'),
    ('d:/project/portfilio/options_pricing/core.py', 'd:/project/portfilio/portfilio-end/app/options/core.py'),
]

for p1, p2 in pairs:
    name = os.path.basename(p1)
    f1 = open(p1, encoding='utf-8').read()
    f2 = open(p2, encoding='utf-8').read()
    identical = f1 == f2
    n1 = f1.count('\n')
    n2 = f2.count('\n')
    status = 'IDENTICAL' if identical else 'DIFF'
    print(f'{name}: {status} ({n1} vs {n2} lines)')
    if not identical:
        # show first diff line
        lines1 = f1.splitlines()
        lines2 = f2.splitlines()
        for i, (a, b) in enumerate(zip(lines1, lines2)):
            if a != b:
                print(f'  first diff at line {i+1}:')
                print(f'    proto: {a[:100]}')
                print(f'    integ: {b[:100]}')
                break
        if len(lines1) != len(lines2):
            print(f'  line count differs: {len(lines1)} vs {len(lines2)}')

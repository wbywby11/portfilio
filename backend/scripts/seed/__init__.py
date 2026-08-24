# -*- coding: utf-8 -*-
"""
生产数据初始化 / 增量导入脚本包

用法：
    # 执行全部初始化（按依赖顺序）
    python -m scripts.seed.runner --data-dir ./data/seed

    # 单独执行某个脚本
    python -m scripts.seed.seed_assets --file ./data/seed/assets.xlsx
    python -m scripts.seed.seed_prices --file ./data/seed/prices.xlsx --dry-run
"""

#!/usr/bin/env python3
"""每 3 小时的“概率提问”掷骰脚本。
命中概率 1/8 -> 打印 HIT 并退出码 0；否则打印 MISS 退出码 1。
只负责掷骰，问题内容与发送交给后面的 LLM 环节。
"""
import random
import sys

P = 1.0 / 8.0
hit = random.random() < P
print("HIT" if hit else "MISS")
print(f"p={P:.4f}", file=sys.stderr)
sys.exit(0 if hit else 1)

"""
数据库初始化脚本

使用方式: cd backend && python ../scripts/init_db.py
"""
import sys
import os

# 添加 backend 目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from models.db import init_db

if __name__ == '__main__':
    init_db()
    print("Done. Database tables created.")

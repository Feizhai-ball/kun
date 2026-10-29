# -*- coding: utf-8 -*-
from app import ensure_indexes
if __name__ == "__main__":
    print("开始为现有 my_data.db 建立索引……")
    ok = ensure_indexes()
    print("索引检查完成。" if ok else "索引初始化未完成，请检查上方提示。")

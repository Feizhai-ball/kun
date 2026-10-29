# -*- coding: utf-8 -*-
"""Flask + SQLite 离线坤关联图谱（适合当前约 12 万条记录）
保留原有 / 与 /search 的参数及 JSON 返回结构；不改写 source_data。
"""
import sqlite3
from pathlib import Path
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DB_NAME = BASE_DIR / "my_data.db"
TABLE_NAME = "source_data"

GRAPH_FIELDS = {"QQ": "QQ", "wechat": "微信", "phone": "电话", "place": "地点"}
RECORD_FIELDS = ["title", "price", "place", "QQ", "wechat", "phone"]


def get_db():
    conn = sqlite3.connect(str(DB_NAME), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def ensure_indexes():
    """只创建辅助索引；不删除、重建或重新导入业务数据。"""
    if not DB_NAME.is_file():
        print(f"[错误] 找不到数据库：{DB_NAME}")
        print("请把原有 my_data.db 放到 app.py 同一目录。")
        return False

    conn = get_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_NAME,),
        ).fetchone()
        if not exists:
            print("[错误] 数据库中没有 source_data 表，停止建索引。")
            return False

        columns = {r["name"] for r in conn.execute('PRAGMA table_info("source_data")')}
        missing = set(RECORD_FIELDS) - columns
        if missing:
            print("[错误] source_data 缺少字段：" + ", ".join(sorted(missing)))
            print("没有修改数据库。请先核对真实字段名。")
            return False

        for col in ("QQ", "wechat", "phone", "place"):
            idx = "idx_source_data_" + col.lower()
            conn.execute(f'CREATE INDEX IF NOT EXISTS "{idx}" ON "source_data"("{col}")')
        conn.execute('CREATE INDEX IF NOT EXISTS "idx_source_data_price" ON "source_data"("price")')
        conn.commit()
        print("[索引] QQ、wechat、phone、place、price 索引检查完成。")
        return True
    except sqlite3.Error as exc:
        conn.rollback()
        print("[索引初始化失败]", exc)
        return False
    finally:
        conn.close()


def safe_int(value, default, minimum=1, maximum=500):
    try:
        return max(minimum, min(maximum, int(value)))
    except (ValueError, TypeError):
        return default


def make_graph_payload(rows, limit):
    has_more = len(rows) > limit
    rows = rows[:limit]
    nodes, edges, seen_fields = [], [], set()

    for row in rows:
        rid = int(row["_rowid"])
        record_id = f"r:{rid}"
        data = {key: row[key] for key in RECORD_FIELDS}
        title = str(row["title"] or "未命名记录")
        place = str(row["place"] or "")
        label = title[:26] + ("…" if len(title) > 26 else "")
        if place:
            label += "\n" + place[:18]

        nodes.append({
            "id": record_id, "type": "record", "label": label,
            "record_id": rid, "data": data,
        })

        for field, display_name in GRAPH_FIELDS.items():
            value = str(row[field] or "").strip()
            if not value:
                continue
            field_id = f"f:{field}:{value}"
            if field_id not in seen_fields:
                seen_fields.add(field_id)
                nodes.append({
                    "id": field_id, "type": "field", "field": field,
                    "field_label": display_name, "value": value,
                    "label": value[:28] + ("…" if len(value) > 28 else ""),
                })
            edges.append({"source": record_id, "target": field_id, "field": field})

    return {
        "nodes": nodes,
        "edges": edges,
        "record_count": len(rows),
        "has_more": has_more,
        "next_cursor": int(rows[-1]["_rowid"]) if rows else None,
    }


def graph_where(keyword, params):
    if not keyword:
        return ""
    pattern = f"%{keyword}%"
    params.extend([pattern] * 5)
    return "(CAST(title AS TEXT) LIKE ? OR CAST(place AS TEXT) LIKE ? OR CAST(QQ AS TEXT) LIKE ? OR CAST(wechat AS TEXT) LIKE ? OR CAST(phone AS TEXT) LIKE ?)"


@app.route("/")
def index():
    # 原有查询页面保持不变
    return render_template("index.html")


@app.route("/search", methods=["GET"])
def search():
    """原 /search 保持原有参数及返回字段：data/total/page/size/total_pages。"""
    conn = get_db()
    try:
        keyword = request.args.get("keyword", "").strip()
        min_price = request.args.get("min_price", "").strip()
        max_price = request.args.get("max_price", "").strip()
        try:
            page = max(1, int(request.args.get("page", 1)))
            size = max(1, min(500, int(request.args.get("size", 50))))
        except (ValueError, TypeError):
            return jsonify({"error": "page 或 size 格式错误"}), 400

        offset = (page - 1) * size
        where_conditions, params = [], []
        if keyword:
            where_conditions.append("(title LIKE ? OR place LIKE ? OR QQ LIKE ? OR wechat LIKE ? OR phone LIKE ?)")
            params.extend([f"%{keyword}%"] * 5)
        if min_price:
            try:
                min_value = float(min_price)
                if min_value < 0:
                    return jsonify({"error": "最低价格不能小于 0"}), 400
                where_conditions.append("price >= ?")
                params.append(min_value)
            except (ValueError, TypeError):
                return jsonify({"error": "min_price 格式错误"}), 400
        if max_price:
            try:
                max_value = float(max_price)
                if max_value < 0:
                    return jsonify({"error": "最高价格不能小于 0"}), 400
                where_conditions.append("price <= ?")
                params.append(max_value)
            except (ValueError, TypeError):
                return jsonify({"error": "max_price 格式错误"}), 400

        where_sql = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME}{where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(f"""
            SELECT title, price, place, QQ, wechat, phone
            FROM {TABLE_NAME}{where_sql}
            ORDER BY CASE WHEN price IS NULL THEN 1 ELSE 0 END, price ASC
            LIMIT ? OFFSET ?
        """, params + [size, offset]).fetchall()
        return jsonify({
            "data": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "size": size,
            "total_pages": (total + size - 1) // size,
        })
    except sqlite3.Error as exc:
        print("数据库错误:", exc)
        return jsonify({"error": "数据库查询失败", "detail": str(exc)}), 500
    except Exception as exc:
        print("程序错误:", exc)
        return jsonify({"error": str(exc)}), 500
    finally:
        conn.close()


@app.route("/graph")
def graph_page():
    return render_template("graph.html")


@app.route("/api/graph", methods=["GET"])
def graph_api():
    """初次加载/分页加载。rowid 游标避免越来越慢的深 OFFSET。"""
    conn = get_db()
    try:
        keyword = request.args.get("keyword", "").strip()
        cursor_text = request.args.get("cursor", "").strip()
        cursor = int(cursor_text) if cursor_text else None
        limit = safe_int(request.args.get("limit", 80), 80, maximum=80)
        params = []
        where = graph_where(keyword, params)
        conditions = [where] if where else []
        if cursor is not None:
            conditions.append("rowid < ?")
            params.append(cursor)
        where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = conn.execute(f"""
            SELECT rowid AS _rowid, title, price, place, QQ, wechat, phone
            FROM {TABLE_NAME}{where_sql}
            ORDER BY rowid DESC LIMIT ?
        """, params + [limit + 1]).fetchall()
        payload = make_graph_payload(rows, limit)
        payload.update({"keyword": keyword, "limit": limit})
        return jsonify(payload)
    except (ValueError, TypeError):
        return jsonify({"error": "cursor 或 limit 参数格式错误"}), 400
    except sqlite3.Error as exc:
        return jsonify({"error": "图谱查询失败", "detail": str(exc)}), 500
    finally:
        conn.close()


@app.route("/api/graph/expand", methods=["GET"])
def graph_expand_api():
    """按记录或字段值扩展关联链，每次最多返回 60 条记录。"""
    conn = get_db()
    try:
        record_id = request.args.get("record_id", "").strip()
        field = request.args.get("field", "").strip()
        value = request.args.get("value", "").strip()
        limit = safe_int(request.args.get("limit", 60), 60, maximum=60)

        if record_id:
            try:
                rid = int(record_id)
            except ValueError:
                return jsonify({"error": "record_id 格式错误"}), 400
            source = conn.execute(
                f"SELECT rowid AS _rowid, title, price, place, QQ, wechat, phone FROM {TABLE_NAME} WHERE rowid=?",
                (rid,),
            ).fetchone()
            if source is None:
                return jsonify({"nodes": [], "edges": [], "record_count": 0, "has_more": False, "next_cursor": None})
            conditions, params = [], []
            for col in GRAPH_FIELDS:
                val = str(source[col] or "").strip()
                if val:
                    conditions.append(f'"{col}" = ?')
                    params.append(val)
            if conditions:
                rows = conn.execute(f"""
                    SELECT rowid AS _rowid, title, price, place, QQ, wechat, phone
                    FROM {TABLE_NAME}
                    WHERE {" OR ".join(conditions)}
                    ORDER BY rowid DESC LIMIT ?
                """, params + [limit + 1]).fetchall()
            else:
                rows = [source]
        elif field and value:
            if field not in GRAPH_FIELDS:
                return jsonify({"error": "不支持的关联字段"}), 400
            rows = conn.execute(f"""
                SELECT rowid AS _rowid, title, price, place, QQ, wechat, phone
                FROM {TABLE_NAME}
                WHERE "{field}" = ?
                ORDER BY rowid DESC LIMIT ?
            """, (value, limit + 1)).fetchall()
        else:
            return jsonify({"error": "请提供 record_id，或同时提供 field 和 value"}), 400

        return jsonify(make_graph_payload(rows, limit))
    except (ValueError, TypeError):
        return jsonify({"error": "参数格式错误"}), 400
    except sqlite3.Error as exc:
        return jsonify({"error": "展开关联失败", "detail": str(exc)}), 500
    finally:
        conn.close()


if __name__ == "__main__":
    ensure_indexes()
    print("原查询页面：http://127.0.0.1:5000/")
    print("坤关联图谱：http://127.0.0.1:5000/graph")
    app.run(debug=False, host="127.0.0.1", port=5000)

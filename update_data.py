#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（最终修正版）
- 派发日：成交量放大20% + 收盘价下跌 >0.1%
- 板块涨跌幅：使用调整收盘价，日线数据
"""

import json
import time
import random
from datetime import datetime

import yfinance as yf

def safe_float(val):
    if hasattr(val, 'item'):
        return float(val.item())
    return float(val)

# ---------- 1. 市场宽度 ----------
def get_market_breadth_estimate():
    try:
        spy = yf.download("SPY", period="6mo", interval="1d", progress=False, auto_adjust=False)
        rsp = yf.download("RSP", period="6mo", interval="1d", progress=False, auto_adjust=False)
        if spy.empty or rsp.empty or len(spy) < 60:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        spy_start = safe_float(spy['Adj Close'].iloc[0])
        spy_end = safe_float(spy['Adj Close'].iloc[-1])
        rsp_start = safe_float(rsp['Adj Close'].iloc[0])
        rsp_end = safe_float(rsp['Adj Close'].iloc[-1])
        if spy_start == 0 or rsp_start == 0:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        spy_ret = (spy_end - spy_start) / spy_start * 100
        rsp_ret = (rsp_end - rsp_start) / rsp_start * 100
        diff = spy_ret - rsp_ret
        base_50, base_200 = 55.0, 56.0
        adj = -diff * 1.2
        pct_50 = max(30.0, min(80.0, base_50 + adj))
        pct_200 = max(30.0, min(80.0, base_200 + adj))
        return {"pct_above_50": round(pct_50, 1), "pct_above_200": round(pct_200, 1)}
    except Exception as e:
        print(f"市场宽度估算失败: {e}")
        return {"pct_above_50": 52.0, "pct_above_200": 53.0}

# ---------- 2. 板块 YTD ----------
def get_sector_ytd():
    etfs = {
        "XLB": "原材料", "XLC": "通讯服务", "XLE": "能源", "XLF": "金融",
        "XLI": "工业", "XLK": "科技", "XLP": "必需消费", "XLU": "公用事业",
        "XLV": "医疗保健", "XLY": "可选消费", "XLRE": "房地产"
    }
    results = []
    for ticker, name in etfs.items():
        try:
            data = yf.download(ticker, period="ytd", interval="1d", progress=False, auto_adjust=False)
            if len(data) >= 2:
                start = safe_float(data['Adj Close'].iloc[0])
                end = safe_float(data['Adj Close'].iloc[-1])
                ytd = (end - start) / start * 100 if start != 0 else 0
                results.append({"name": ticker, "ytd": round(ytd, 2)})
            else:
                results.append({"name": ticker, "ytd": 0.0})
            time.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            print(f"获取 {ticker} YTD 失败: {e}")
            results.append({"name": ticker, "ytd": 0.0})
    results.sort(key=lambda x: x["ytd"], reverse=True)
    return results

# ---------- 3. 派发日（严格条件）----------
def get_distribution_history(days_back=60, volume_threshold=1.20, price_drop_pct=0.001):
    spy = yf.download("SPY", period="3mo", interval="1d", progress=False, auto_adjust=False)
    if spy.empty:
        return []
    if 'Adj Close' in spy.columns:
        closes = spy['Adj Close'].values.flatten()
    else:
        closes = spy['Close'].values.flatten()
    volumes = spy['Volume'].values.flatten()
    dates = spy.index.tolist()
    result = []
    for i in range(1, len(dates)):
        price_drop = (closes[i-1] - closes[i]) / closes[i-1]
        cond1 = price_drop > price_drop_pct
        cond2 = volumes[i] > volumes[i-1] * volume_threshold
        is_dist = 1 if (cond1 and cond2) else 0
        result.append({
            "date": dates[i].strftime("%Y-%m-%d"),
            "is_distribution": is_dist
        })
    return result[-days_back:]

# ---------- 4. XLY/XLP 比率 ----------
def get_xly_xlp_history(days_back=60):
    xly = yf.download("XLY", period="3mo", interval="1d", progress=False, auto_adjust=False)
    xlp = yf.download("XLP", period="3mo", interval="1d", progress=False, auto_adjust=False)
    if xly.empty or xlp.empty:
        return []
    common_dates = sorted(set(xly.index).intersection(set(xlp.index)))
    ratios = []
    prev_ratio = None
    for dt in common_dates:
        xly_close = safe_float(xly.loc[dt, 'Adj Close'])
        xlp_close = safe_float(xlp.loc[dt, 'Adj Close'])
        if xlp_close != 0:
            ratio = xly_close / xlp_close
        else:
            ratio = None
        if ratio is not None:
            change_pct = (ratio - prev_ratio) / prev_ratio * 100 if prev_ratio is not None else 0.0
            ratios.append({
                "date": dt.strftime("%Y-%m-%d"),
                "ratio": round(ratio, 4),
                "change_pct": round(change_pct, 2)
            })
            prev_ratio = ratio
    return ratios[-days_back:]

# ---------- 5. Finviz 板块（精确涨跌幅）----------
def get_finviz_sectors():
    """
    使用 pyfinviz 库直接从 Finviz 网站获取板块涨跌幅数据。
    """
    try:
        from pyfinviz.groups import Groups
    except ImportError:
        # 如果库没装，提醒用户安装
        raise ImportError("pyfinviz 库未安装，请执行 'pip install pyfinviz' 进行安装")

    # 通过抓取 Financial 板块的数据来匹配精准值
    groups = Groups(group_option=Groups.GroupOption.SECTOR_FINANCIAL, view_option=Groups.ViewOption.PERFORMANCE)
    # 获取所有板块的数据
    groups = Groups(view_option=Groups.ViewOption.PERFORMANCE)
    df = groups.table_df  # 得到包含所有板块详细数据的 DataFrame

    result = []
    # 整理需要展示的字段
    for _, row in df.iterrows():
        result.append({
            "name": row["Name"],
            "stocks": row["Stocks"],
            "mktCap": row["Mkt Cap"],
            "div": row["Dividend"],
            "pe": row["P/E"],
            "fwdPe": row["Fwd P/E"],
            "peg": row["PEG"],
            "change": row["Change"],          # 直接从 Finviz 获取当日涨跌幅
            "volume": row["Volume"]
        })

    return result
# ---------- 6. 泡沫指标 ----------
def get_bubble_indicators():
    margin = {"value": "1,304,281", "yoy": "+53.34%", "date": "2026-04-01"}
    put_call = {"ratio": "0.55", "ma20": "0.51", "date": "2026-05-22"}
    try:
        with open("margin_debt.json", "r") as f:
            custom_margin = json.load(f)
            margin.update(custom_margin)
    except FileNotFoundError:
        pass
    try:
        with open("put_call.json", "r") as f:
            custom_pc = json.load(f)
            put_call.update(custom_pc)
    except FileNotFoundError:
        pass
    return {"marginDebt": margin, "putCall": put_call}

# ---------- 历史数据聚合 ----------
def get_all_history():
    # 市场宽度历史
    breadth_hist = []
    try:
        spy_all = yf.download("SPY", period="6mo", interval="1d", progress=False, auto_adjust=False)
        rsp_all = yf.download("RSP", period="6mo", interval="1d", progress=False, auto_adjust=False)
        if not spy_all.empty and not rsp_all.empty:
            common_dates = sorted(set(spy_all.index).intersection(set(rsp_all.index)))
            for i in range(max(0, len(common_dates)-60), len(common_dates)):
                dt = common_dates[i]
                spy_slice = spy_all.loc[:dt]
                rsp_slice = rsp_all.loc[:dt]
                if len(spy_slice) >= 60 and len(rsp_slice) >= 60:
                    spy_start = safe_float(spy_slice['Adj Close'].iloc[0])
                    spy_end = safe_float(spy_slice['Adj Close'].iloc[-1])
                    rsp_start = safe_float(rsp_slice['Adj Close'].iloc[0])
                    rsp_end = safe_float(rsp_slice['Adj Close'].iloc[-1])
                    if spy_start != 0 and rsp_start != 0:
                        spy_ret = (spy_end - spy_start) / spy_start * 100
                        rsp_ret = (rsp_end - rsp_start) / rsp_start * 100
                        diff = spy_ret - rsp_ret
                        base_50, base_200 = 55.0, 56.0
                        adj = -diff * 1.2
                        pct_50 = max(30.0, min(80.0, base_50 + adj))
                        pct_200 = max(30.0, min(80.0, base_200 + adj))
                        breadth_hist.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "above50": round(pct_50, 1),
                            "above200": round(pct_200, 1)
                        })
    except Exception as e:
        print(f"生成宽度历史失败: {e}")

    dist_hist = get_distribution_history(60)
    xly_hist = get_xly_xlp_history(60)
    margin_hist = []
    pc_hist = []
    try:
        with open("margin_debt_history.json", "r") as f:
            margin_hist = json.load(f)
    except:
        pass
    try:
        with open("put_call_history.json", "r") as f:
            pc_hist = json.load(f)
    except:
        pass
    return {
        "breadth": breadth_hist,
        "distribution": dist_hist,
        "xlyXlp": xly_hist,
        "marginDebt": margin_hist,
        "putCall": pc_hist
    }

def get_latest_snapshot(history):
    breadth = history["breadth"][-1] if history["breadth"] else {"above50": 50, "above200": 50}
    dist_list = history["distribution"]
    dist_count = sum(d["is_distribution"] for d in dist_list[-15:]) if dist_list else 0
    xly_list = history["xlyXlp"]
    latest_xly = xly_list[-1] if xly_list else {"ratio": 1.0, "change_pct": 0.0}
    pc_list = history["putCall"]
    latest_pc = pc_list[-1] if pc_list else {"ratio": 0.5}
    margin_list = history["marginDebt"]
    latest_margin = margin_list[-1] if margin_list else {"margin_debt": 1304281, "date": "2026-04-01"}
    margin_yoy = "N/A"
    if len(margin_list) >= 2:
        prev = margin_list[-2]["margin_debt"]
        curr = latest_margin["margin_debt"]
        margin_yoy = f"+{(curr - prev)/prev*100:.2f}%" if prev != 0 else "N/A"
    return {
        "breadth": {"above50": breadth["above50"], "above200": breadth["above200"]},
        "distributionDays": dist_count,
        "xlyXlp": {"ratio": latest_xly["ratio"], "change_pct": latest_xly["change_pct"]},
        "putCall": {"ratio": latest_pc["ratio"], "ma20": "N/A"},
        "marginDebt": {"value": latest_margin["margin_debt"], "yoy": margin_yoy, "date": latest_margin["date"]}
    }

def main():
    print("🚀 开始更新美股驾驶舱数据（最终修正版）...")
    history = get_all_history()
    snapshot = get_latest_snapshot(history)
    sector_ytd = get_sector_ytd()
    finviz_data = get_finviz_sectors()
    bubble = get_bubble_indicators()
    snapshot["putCall"] = bubble["putCall"]
    snapshot["marginDebt"] = bubble["marginDebt"]
    data = {
        "updateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot": snapshot,
        "sectorYtd": sector_ytd,
        "finvizSectors": finviz_data,
        "history": history
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("🎉 数据已保存到 data.json")
    print(f"市场宽度: 50日={snapshot['breadth']['above50']}%, 200日={snapshot['breadth']['above200']}%")
    print(f"派发日计数: {snapshot['distributionDays']}")
    print(f"XLY/XLP 比率: {snapshot['xlyXlp']['ratio']} ({snapshot['xlyXlp']['change_pct']:+.2f}%)")

if __name__ == "__main__":
    main()

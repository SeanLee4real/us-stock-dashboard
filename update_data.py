#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（最终稳定版）
无 DataFrame 列间比较，全部使用 Python 列表，避免对齐错误。
"""

import json
import time
import random
from datetime import datetime, timedelta

import yfinance as yf

# ---------- 辅助：安全获取收盘价 ----------
def get_close(data, idx):
    """从 yfinance 下载的 DataFrame 中安全获取收盘价"""
    try:
        return float(data['Close'].iloc[idx])
    except:
        return 0.0

# ---------- 1. 市场宽度估算（基于 SPY vs RSP 60日收益率差）----------
def get_market_breadth_estimate():
    try:
        spy = yf.download("SPY", period="6mo", progress=False)
        rsp = yf.download("RSP", period="6mo", progress=False)
        if spy.empty or rsp.empty or len(spy) < 60 or len(rsp) < 60:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        spy_start = get_close(spy, 0)
        spy_end = get_close(spy, -1)
        rsp_start = get_close(rsp, 0)
        rsp_end = get_close(rsp, -1)
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
            data = yf.download(ticker, period="ytd", progress=False)
            if len(data) >= 2:
                start = get_close(data, 0)
                end = get_close(data, -1)
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

# ---------- 3. 派发日历史（纯列表循环，无 DataFrame 比较）----------
def get_distribution_history(days_back=60):
    """返回过去 days_back 天的派发日标记列表"""
    spy = yf.download("SPY", period="3mo", progress=False)
    if spy.empty:
        return []
    # 提取日期、收盘价、成交量到列表
    dates = spy.index.tolist()
    closes = [float(x) for x in spy['Close'].tolist()]
    volumes = [int(x) for x in spy['Volume'].tolist()]
    result = []
    for i in range(1, len(dates)):
        is_dist = 1 if (closes[i] < closes[i-1] and volumes[i] > volumes[i-1]) else 0
        result.append({
            "date": dates[i].strftime("%Y-%m-%d"),
            "is_distribution": is_dist
        })
    # 只返回最近 days_back 天
    return result[-days_back:]

# ---------- 4. XLY/XLP 比率历史（纯列表）----------
def get_xly_xlp_history(days_back=60):
    xly = yf.download("XLY", period="3mo", progress=False)
    xlp = yf.download("XLP", period="3mo", progress=False)
    if xly.empty or xlp.empty:
        return []
    # 对齐日期（取交集）
    common_dates = sorted(set(xly.index).intersection(set(xlp.index)))
    ratios = []
    prev_ratio = None
    for dt in common_dates:
        xly_close = float(xly.loc[dt, 'Close'])
        xlp_close = float(xlp.loc[dt, 'Close'])
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

# ---------- 5. Finviz 板块数据（实时涨跌幅）----------
def get_finviz_sectors():
    sector_etfs = {
        "科技": "XLK", "金融": "XLF", "医疗保健": "XLV", "可选消费": "XLY",
        "必需消费": "XLP", "工业": "XLI", "能源": "XLE", "原材料": "XLB",
        "公用事业": "XLU", "房地产": "XLRE", "通讯服务": "XLC"
    }
    static_data = {
        "科技": {"pe": "38.6", "peg": "1.19", "stocks": "779", "mktCap": "31.1T", "div": "0.54%"},
        "金融": {"pe": "16.0", "peg": "1.38", "stocks": "1092", "mktCap": "13.9T", "div": "1.97%"},
        "医疗保健": {"pe": "28.8", "peg": "2.02", "stocks": "1075", "mktCap": "8.33T", "div": "1.60%"},
        "可选消费": {"pe": "30.4", "peg": "1.56", "stocks": "545", "mktCap": "9.36T", "div": "0.78%"},
        "必需消费": {"pe": "26.9", "peg": "2.94", "stocks": "246", "mktCap": "4.49T", "div": "2.37%"},
        "工业": {"pe": "32.0", "peg": "1.67", "stocks": "690", "mktCap": "7.59T", "div": "1.08%"},
        "能源": {"pe": "19.8", "peg": "1.39", "stocks": "256", "mktCap": "4.74T", "div": "3.43%"},
        "原材料": {"pe": "22.7", "peg": "1.24", "stocks": "283", "mktCap": "2.88T", "div": "1.94%"},
        "公用事业": {"pe": "21.0", "peg": "1.79", "stocks": "109", "mktCap": "1.96T", "div": "2.93%"},
        "房地产": {"pe": "32.7", "peg": "3.34", "stocks": "255", "mktCap": "1.80T", "div": "3.72%"},
        "通讯服务": {"pe": "39.1", "peg": "2.23", "stocks": "263", "mktCap": "13.7T", "div": "0.50%"},
    }
    result = []
    for name, ticker in sector_etfs.items():
        change_str = "0.00%"
        vol_str = "N/A"
        try:
            data = yf.download(ticker, period="2d", progress=False)
            if len(data) >= 2:
                prev = get_close(data, -2)
                curr = get_close(data, -1)
                if prev != 0:
                    change = (curr - prev) / prev * 100
                    change_str = f"{'+' if change >= 0 else ''}{change:.2f}%"
                vol = int(data['Volume'].iloc[-1]) if len(data) > 0 else 0
                if vol > 1e9:
                    vol_str = f"{vol/1e9:.2f}B"
                elif vol > 1e6:
                    vol_str = f"{vol/1e6:.0f}M"
                else:
                    vol_str = str(vol)
        except Exception as e:
            print(f"获取 {name} 实时涨跌幅失败: {e}")
        info = static_data.get(name, {})
        result.append({
            "name": name,
            "stocks": info.get("stocks", "-"),
            "mktCap": info.get("mktCap", "-"),
            "div": info.get("div", "-"),
            "pe": info.get("pe", "-"),
            "fwdPe": info.get("fwdPe", "-"),
            "peg": info.get("peg", "-"),
            "change": change_str,
            "volume": vol_str
        })
    return result

# ---------- 6. 泡沫指标（手动维护）----------
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

# ---------- 获取所有历史数据 ----------
def get_all_history():
    # 市场宽度历史（过去60天每日估算）
    breadth_hist = []
    try:
        spy_all = yf.download("SPY", period="6mo", progress=False)
        rsp_all = yf.download("RSP", period="6mo", progress=False)
        if not spy_all.empty and not rsp_all.empty:
            common_dates = sorted(set(spy_all.index).intersection(set(rsp_all.index)))
            for i in range(max(0, len(common_dates)-60), len(common_dates)):
                dt = common_dates[i]
                spy_slice = spy_all.loc[:dt]
                rsp_slice = rsp_all.loc[:dt]
                if len(spy_slice) >= 60 and len(rsp_slice) >= 60:
                    spy_start = get_close(spy_slice, 0)
                    spy_end = get_close(spy_slice, -1)
                    rsp_start = get_close(rsp_slice, 0)
                    rsp_end = get_close(rsp_slice, -1)
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
        breadth_hist = []

    # 派发日历史
    dist_hist = get_distribution_history(60)
    # XLY/XLP 历史
    xly_hist = get_xly_xlp_history(60)
    # 泡沫历史（手动）
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

# ---------- 最新快照 ----------
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

# ---------- 主函数 ----------
def main():
    print("🚀 开始更新美股驾驶舱数据（最终稳定版）...")
    history = get_all_history()
    snapshot = get_latest_snapshot(history)
    sector_ytd = get_sector_ytd()
    finviz_data = get_finviz_sectors()
    bubble = get_bubble_indicators()  # 手动泡沫快照（覆盖）

    # 将手动泡沫数据合并到 snapshot
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

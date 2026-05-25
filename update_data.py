#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股驾驶舱数据更新脚本（稳定版 - 无外部API依赖）
市场宽度基于 SPY vs RSP 估算，派发日修复对齐错误，泡沫数据支持手动覆盖。
"""

import json
import time
import random
from datetime import datetime

import yfinance as yf
import pandas as pd

# ---------- 辅助函数 ----------
def safe_scalar(series, default=0.0):
    if isinstance(series, pd.Series):
        val = series.iloc[-1] if len(series) > 0 else default
    elif isinstance(series, (pd.DataFrame, pd.Index)):
        val = series.iloc[-1] if len(series) > 0 else default
    else:
        val = series
    return float(val) if not pd.isna(val) else default

def safe_shift(series, periods):
    """安全的 shift，返回 Series，索引不变"""
    return series.shift(periods)

# ---------- 1. 市场宽度（估算）----------
def get_market_breadth_estimate():
    """
    基于 SPY 与 RSP (等权重 S&P500) 过去60日收益率差估算市场宽度。
    当 SPY 跑赢 RSP 越多（巨头行情），宽度越低；反之宽度越高。
    """
    try:
        spy = yf.download("SPY", period="3mo", progress=False)
        rsp = yf.download("RSP", period="3mo", progress=False)
        if spy.empty or rsp.empty or len(spy) < 60 or len(rsp) < 60:
            return {"pct_above_50": 52.0, "pct_above_200": 53.0}
        spy_ret = (safe_scalar(spy["Close"].iloc[-1]) - safe_scalar(spy["Close"].iloc[0])) / safe_scalar(spy["Close"].iloc[0]) * 100
        rsp_ret = (safe_scalar(rsp["Close"].iloc[-1]) - safe_scalar(rsp["Close"].iloc[0])) / safe_scalar(rsp["Close"].iloc[0]) * 100
        diff = spy_ret - rsp_ret
        # 基线：正常市场宽度约55%
        base_50, base_200 = 55.0, 56.0
        adj = -diff * 1.2  # 调整系数
        pct_50 = max(30, min(80, base_50 + adj))
        pct_200 = max(30, min(80, base_200 + adj))
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
                start = safe_scalar(data["Close"].iloc[0])
                end = safe_scalar(data["Close"].iloc[-1])
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

# ---------- 3. 派发日历史（修复对齐错误）----------
def get_distribution_history(days_back=60):
    """返回过去 days_back 天的派发日标记列表"""
    spy = yf.download("SPY", period="3mo", progress=False)
    if spy.empty:
        return []
    # 确保索引是时间序列
    spy = spy.sort_index()
    spy["VolumePrev"] = spy["Volume"].shift(1)
    # 关键修复：使用 .values 或直接比较，避免索引对齐问题
    spy["CloseDown"] = (spy["Close"] < spy["Close"].shift(1)).astype(int)
    spy["VolumeUp"] = (spy["Volume"] > spy["VolumePrev"]).astype(int)
    spy["Distribution"] = spy["CloseDown"] & spy["VolumeUp"]
    # 转为列表
    result = []
    for idx, row in spy.iterrows():
        result.append({
            "date": idx.strftime("%Y-%m-%d"),
            "is_distribution": int(row["Distribution"])
        })
    # 返回最近 days_back 天
    return result[-days_back:]

# ---------- 4. XLY/XLP 比率历史 ----------
def get_xly_xlp_history(days_back=60):
    xly = yf.download("XLY", period="3mo", progress=False)
    xlp = yf.download("XLP", period="3mo", progress=False)
    if xly.empty or xlp.empty:
        return []
    # 合并索引
    common_dates = xly.index.intersection(xlp.index)
    ratios = []
    prev_ratio = None
    for date in common_dates:
        xly_close = safe_scalar(xly.loc[date, "Close"])
        xlp_close = safe_scalar(xlp.loc[date, "Close"])
        if xlp_close != 0:
            ratio = xly_close / xlp_close
        else:
            ratio = None
        if ratio is not None:
            change_pct = (ratio - prev_ratio) / prev_ratio * 100 if prev_ratio is not None else 0.0
            ratios.append({
                "date": date.strftime("%Y-%m-%d"),
                "ratio": round(ratio, 4),
                "change_pct": round(change_pct, 2) if prev_ratio is not None else 0.0
            })
            prev_ratio = ratio
    return ratios[-days_back:]

# ---------- 5. Finviz 板块数据（实时涨跌幅 + 静态估值）----------
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
                prev = safe_scalar(data["Close"].iloc[-2])
                curr = safe_scalar(data["Close"].iloc[-1])
                if prev != 0:
                    change = (curr - prev) / prev * 100
                    change_str = f"{'+' if change >= 0 else ''}{change:.2f}%"
                vol = safe_scalar(data["Volume"].iloc[-1], default=0)
                if vol > 1e9:
                    vol_str = f"{vol/1e9:.2f}B"
                elif vol > 1e6:
                    vol_str = f"{vol/1e6:.0f}M"
                else:
                    vol_str = f"{vol:.0f}"
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

# ---------- 6. 泡沫指标（支持手动覆盖）----------
def get_bubble_indicators():
    # 默认值（用户可手动更新 margin_debt.json 和 put_call.json）
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

# ---------- 最新快照 ----------
def get_latest_snapshot(history):
    """从历史数据中提取最新值"""
    # 市场宽度
    breadth = history["breadth"][-1] if history["breadth"] else {"pct_above_50": 50, "pct_above_200": 50}
    # 派发日计数（过去15天）
    dist_hist = history["distribution"]
    dist_count = sum(d["is_distribution"] for d in dist_hist[-15:]) if dist_hist else 0
    # XLY/XLP
    xly_hist = history["xlyXlp"]
    latest_xly = xly_hist[-1] if xly_hist else {"ratio": 1.0, "change_pct": 0.0}
    # Put/Call
    pc_hist = history["putCall"]
    latest_pc = pc_hist[-1] if pc_hist else {"ratio": 0.5}
    # 保证金债务
    margin_hist = history["marginDebt"]
    latest_margin = margin_hist[-1] if margin_hist else {"margin_debt": 1304281, "date": "2026-04-01"}
    # 计算同比增长
    margin_yoy = "N/A"
    if len(margin_hist) >= 2:
        prev = margin_hist[-2]["margin_debt"]
        curr = latest_margin["margin_debt"]
        margin_yoy = f"+{(curr - prev)/prev*100:.2f}%" if prev != 0 else "N/A"
    return {
        "breadth": {"above50": breadth["pct_above_50"], "above200": breadth["pct_above_200"]},
        "distributionDays": dist_count,
        "xlyXlp": {"ratio": latest_xly["ratio"], "change_pct": latest_xly["change_pct"]},
        "putCall": {"ratio": latest_pc["ratio"], "ma20": latest_pc.get("ma20", "N/A")},
        "marginDebt": {"value": latest_margin["margin_debt"], "yoy": margin_yoy, "date": latest_margin["date"]}
    }

# ---------- 主函数 ----------
def main():
    print("🚀 开始更新美股驾驶舱数据（稳定版）...")
    
    # 获取各历史数据
    breadth_hist = []
    # 每日估算市场宽度（过去60天）
    end_date = datetime.now()
    for i in range(60, 0, -1):
        # 为简化，我们只存储最近一次估算值，历史数据用 same 模拟？不，最好从 yfinance 逐日计算
        # 为了性能，我们仅计算今天的数据，历史宽度不存储（因为无法精确回溯），前端可显示近期估算
        # 更好的：我们存储每天的估算值，通过下载每日数据计算。但那样开销大。简化：历史只存最近60天的估算值，
        # 我们通过循环计算每一天的 SPY/RSP 价格，但比较复杂。保守做法：前端只显示当前值，不显示历史折线。
        # 由于你要求折线图，我们至少要有历史数据。我们采用每日计算过去60天的宽度估算（基于当日之前60日回报）。
        # 这样每次运行脚本时会计算最近60天的宽度（可以做到）。
        pass
    # 实际上为了简化并保证运行，我们仅提供当前宽度，历史宽度使用重复当前值（或未来改进）
    # 更好的：我们使用 yfinance 下载历史日线，然后滚动计算每日宽度。
    # 这里实现一个高效版本：
    try:
        spy_all = yf.download("SPY", period="6mo", progress=False)
        rsp_all = yf.download("RSP", period="6mo", progress=False)
        if not spy_all.empty and not rsp_all.empty:
            common_dates = spy_all.index.intersection(rsp_all.index)
            breadth_hist = []
            for i in range(60, 0, -1):
                if i >= len(common_dates):
                    continue
                date = common_dates[-i]
                spy_slice = spy_all.loc[:date]
                rsp_slice = rsp_all.loc[:date]
                if len(spy_slice) >= 60 and len(rsp_slice) >= 60:
                    spy_ret = (spy_slice["Close"].iloc[-1] - spy_slice["Close"].iloc[0]) / spy_slice["Close"].iloc[0] * 100
                    rsp_ret = (rsp_slice["Close"].iloc[-1] - rsp_slice["Close"].iloc[0]) / rsp_slice["Close"].iloc[0] * 100
                    diff = spy_ret - rsp_ret
                    base_50, base_200 = 55.0, 56.0
                    adj = -diff * 1.2
                    pct_50 = max(30, min(80, base_50 + adj))
                    pct_200 = max(30, min(80, base_200 + adj))
                    breadth_hist.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "above50": round(pct_50, 1),
                        "above200": round(pct_200, 1)
                    })
            # 反转，使日期从早到晚
            breadth_hist.reverse()
    except Exception as e:
        print(f"生成宽度历史失败: {e}")
        breadth_hist = []
    
    # 其他历史
    dist_hist = get_distribution_history(60)
    xly_hist = get_xly_xlp_history(60)
    # 泡沫历史默认空，需要手动提供
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
    
    # 板块 YTD
    sector_ytd = get_sector_ytd()
    finviz_data = get_finviz_sectors()
    
    # 构建 history 字典
    history = {
        "breadth": breadth_hist,
        "distribution": dist_hist,
        "xlyXlp": xly_hist,
        "marginDebt": margin_hist,
        "putCall": pc_hist
    }
    
    snapshot = get_latest_snapshot(history)
    
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
    print(f"XLY/XLP比率: {snapshot['xlyXlp']['ratio']} ({snapshot['xlyXlp']['change_pct']:+.2f}%)")

if __name__ == "__main__":
    main()

def get_positions(memory):
    return memory["positions"]


def get_stock_data(stock_code):
    # 先假数据，后面再接真实行情
    return {
        "code": stock_code,
        "price": 123.45,
        "change": "+2.3%"
    }


def search_history(memory, keyword):
    results = []

    for item in memory["history"]:
        if keyword.lower() in str(item).lower():
            results.append(item)

    return results
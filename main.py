from memory import load_memory
from tools import get_positions, get_stock_data

memory = load_memory()

while True:

    user_input = input("You: ")

    if user_input == "持仓":
        print(get_positions(memory))

    elif user_input.startswith("股票 "):

        stock_code = user_input.split(" ")[1]

        result = get_stock_data(stock_code)

        print(result)

    elif user_input == "exit":
        break

    else:
        print("暂时无法理解")
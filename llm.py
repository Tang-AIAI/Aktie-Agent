from openai import OpenAI

client = OpenAI(
    api_key="你的DEEPSEEK_API_KEY",
    base_url="https://api.deepseek.com"
)

def ask_llm(user_input):

    response = client.chat.completions.create(
        model="deepseek-chat",

        messages=[
            {
                "role": "system",
                "content": "你是一个股票AI助手，只负责理解用户问题并给出分析建议"
            },
            {
                "role": "user",
                "content": user_input
            }
        ]
    )

    return response.choices[0].message.content
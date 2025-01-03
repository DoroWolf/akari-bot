import io
import os
import re

from PIL import Image as PILImage

from core.builtins import Bot, I18NContext, Image, Plain
from core.component import module
from core.config import Config
from core.constants.exceptions import ConfigValueError
from core.dirty_check import check_bool, rickroll
from core.utils.cooldown import CoolDown
from .petal import count_token_petal

os.environ["LANGCHAIN_TRACING_V2"] = str(Config("enable_langsmith"))
if Config("enable_langsmith"):
    os.environ["LANGCHAIN_ENDPOINT"] = Config("langsmith_endpoint")
    os.environ["LANGCHAIN_PROJECT"] = Config("langsmith_project")
    os.environ["LANGCHAIN_API_KEY"] = Config("langsmith_api_key")

    from langchain.callbacks import get_openai_callback  # noqa: E402
    from .agent import agent_executor  # noqa: E402
    from .formatting import generate_latex, generate_code_snippet  # noqa: E402

    a = module("ask", developers=["Dianliang233"], desc="{ask.help.desc}", doc=True)

    @a.command("[--verbose] <question> {{ask.help}}")
    @a.regex(
        r"^(?:question||问|問)[\:：]\s?(.+?)[?？]$", flags=re.I, desc="{ask.help.regex}"
    )
    async def _(msg: Bot.MessageSession):
        is_superuser = msg.check_super_user()
        if not Config("openai_api_key", secret=True):
            raise ConfigValueError(msg.locale.t("error.config.secret.not_found"))
        if not is_superuser and msg.petal <= 0:  # refuse
            await msg.finish(msg.locale.t("petal.message.cost.not_enough"))

        qc = CoolDown("call_openai", msg)
        c = qc.check(60)
        if c == 0 or msg.target.client_name == "TEST" or is_superuser:
            if hasattr(msg, "parsed_msg"):
                question = msg.parsed_msg["<question>"]
            else:
                question = msg.matched_msg[0]
            if await check_bool(question):
                await msg.finish(rickroll(msg))
            with get_openai_callback() as cb:
                res = await agent_executor.arun(question)
                tokens = cb.total_tokens
            if not is_superuser:
                petal = await count_token_petal(msg, tokens)
            else:
                petal = 0

            blocks = parse_markdown(res)

            chain = []
            for block in blocks:
                if block["type"] == "text":
                    chain.append(Plain(block["content"]))
                elif block["type"] == "latex":
                    content = await generate_latex(block["content"])
                    try:
                        img = PILImage.open(io.BytesIO(content))
                        chain.append(Image(img))
                    except Exception:
                        chain.append(
                            I18NContext("ask.message.text2img.error", text=content)
                        )
                elif block["type"] == "code":
                    content = block["content"]["code"]
                    try:
                        chain.append(
                            Image(
                                PILImage.open(
                                    io.BytesIO(
                                        await generate_code_snippet(
                                            content, block["content"]["language"]
                                        )
                                    )
                                )
                            )
                        )
                    except Exception:
                        chain.append(
                            I18NContext("ask.message.text2img.error", text=content)
                        )

            if await check_bool(res):
                await msg.finish(
                    f"{rickroll(msg)}\n{msg.locale.t('petal.message.cost', amount=petal)}"
                )
            if petal != 0:
                chain.append(I18NContext("petal.message.cost", amount=petal))

            if msg.target.client_name != "TEST" and not is_superuser:
                qc.reset()

            await msg.finish(chain)
        else:
            await msg.finish(msg.locale.t("message.cooldown", time=int(60 - c)))

    def parse_markdown(md: str):
        regex = r"(```[\s\S]*?\n```|\$[\s\S]*?\$|[^\n]+)"

        blocks = []
        for match in re.finditer(regex, md):
            content = match.group(1)
            print(content)
            if content.startswith("```"):
                block = "code"
                try:
                    language, code = re.match(
                        r"```(.*)\n([\s\S]*?)\n```", content
                    ).groups()
                except AttributeError:
                    raise ValueError("Code block is missing language or code")
                content = {"language": language, "code": code}
            elif content.startswith("$"):
                block = "latex"
                content = content[1:-1].strip()
            else:
                block = "text"
            blocks.append({"type": block, "content": content})

        return blocks

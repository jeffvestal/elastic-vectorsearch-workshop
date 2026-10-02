import os, asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright
KB=os.environ["ES_KIBANA_URL"].rstrip("/"); KEY=os.environ["ES_API_KEY"]; HOST=urlparse(KB).hostname
OUT=os.path.dirname(os.path.abspath(__file__))+"/out/ui/agent-direct/"
Q="My Elasticsearch container keeps dying with exit code 137. Why does that happen, and what specific JVM and memory settings should I change to prevent it?"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await (await b.new_context(viewport={"width":1600,"height":1000})).new_page()
        async def route(r):
            h=dict(r.request.headers)
            if urlparse(r.request.url).hostname==HOST: h["Authorization"]="ApiKey "+KEY
            await r.continue_(headers=h)
        await pg.route("**/*",route)
        await pg.goto(KB+"/app/agent_builder/agents/workshop-docs-agent",wait_until="domcontentloaded"); await pg.wait_for_timeout(6000)
        await pg.locator("[aria-label^='Select connector']").first.click(); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=OUT+"05-model-picker.png")
        opt=pg.get_by_text("Claude Sonnet 4.5",exact=False).first
        print("sonnet option present:", await opt.count()>0)
        await opt.click(); await pg.wait_for_timeout(1000)
        print("picker now:", await pg.locator("[aria-label^='Select connector']").first.get_attribute("aria-label"))
        await pg.mouse.click(995,530); await pg.keyboard.type(Q,delay=3); await pg.keyboard.press("Enter")
        await pg.wait_for_timeout(60000)
        await pg.mouse.move(1000,400)
        for _ in range(15): await pg.mouse.wheel(0,-2000); await pg.wait_for_timeout(150)
        await pg.screenshot(path=OUT+"06-sonnet-answer-top.png")
        txt=await pg.locator("body").inner_text(); print("search chips:", txt.count("tool: search-workshop-docs-hybrid"))
        await b.close()
asyncio.run(main())

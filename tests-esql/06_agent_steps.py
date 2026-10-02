import os, asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright
KB=os.environ["ES_KIBANA_URL"].rstrip("/"); KEY=os.environ["ES_API_KEY"]; HOST=urlparse(KB).hostname
OUT=os.path.dirname(os.path.abspath(__file__))+"/out/ui/agent-direct/"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await (await b.new_context(viewport={"width":1600,"height":1000})).new_page()
        async def route(r):
            h=dict(r.request.headers)
            if urlparse(r.request.url).hostname==HOST: h["Authorization"]="ApiKey "+KEY
            await r.continue_(headers=h)
        await pg.route("**/*",route)
        await pg.goto(KB+"/app/agent_builder/agents/workshop-docs-agent",wait_until="domcontentloaded"); await pg.wait_for_timeout(6000)
        await pg.mouse.click(995,530); await pg.keyboard.type("My Elasticsearch container keeps dying with exit code 137. Why does that happen, and what specific JVM and memory settings should I change to prevent it?",delay=3); await pg.keyboard.press("Enter")
        await pg.wait_for_timeout(45000)
        # scroll answer to top and screenshot (reasoning/steps usually sit above the answer)
        await pg.mouse.move(1000,400)
        for _ in range(15): await pg.mouse.wheel(0,-2000); await pg.wait_for_timeout(150)
        await pg.screenshot(path=OUT+"03-answer-top.png")
        btns=pg.locator("button[aria-label], [role=button][aria-label]")
        labels=[await btns.nth(i).get_attribute("aria-label") for i in range(await btns.count())]
        print("aria-labels:", [l for l in labels if l][:80])
        await pg.mouse.move(1000,600); el=pg.locator("[aria-label='Show execution details']").last; await el.wait_for(state="attached",timeout=60000); await el.scroll_into_view_if_needed(); await el.click(force=True); await pg.wait_for_timeout(2500)
        await pg.screenshot(path=OUT+"04-execution-details.png")
        txt=await pg.locator("body").inner_text(); print("search mentions:", txt.count("search-workshop-docs-hybrid"))
        await b.close()
asyncio.run(main())

import os, asyncio, json, time
from urllib.parse import urlparse
from playwright.async_api import async_playwright
KB=os.environ["ES_KIBANA_URL"].rstrip("/"); KEY=os.environ["ES_API_KEY"]; HOST=urlparse(KB).hostname
OUT=os.path.dirname(os.path.abspath(__file__))+"/out/ui/agent-direct/"
Q='My Elasticsearch container keeps dying with exit code 137. Why does that happen, and what specific JVM and memory settings should I change to prevent it?'
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); ctx=await b.new_context(viewport={"width":1600,"height":1000}); pg=await ctx.new_page()
        async def route(r):
            h=dict(r.request.headers)
            if urlparse(r.request.url).hostname==HOST: h["Authorization"]="ApiKey "+KEY
            await r.continue_(headers=h)
        await pg.route("**/*",route)
        await pg.goto(KB+"/app/agent_builder/agents/workshop-docs-agent",wait_until="domcontentloaded"); await pg.wait_for_timeout(8000)
        await pg.screenshot(path=OUT+"01-landing.png"); print("url",pg.url)
        hdr=await pg.locator("body").inner_text(); print("workshop visible:", "Workshop Docs Agent" in hdr)
        await pg.mouse.click(995, 530)
        await pg.keyboard.type(Q, delay=5); await pg.wait_for_timeout(500)
        await pg.screenshot(path=OUT+"01b-typed.png")
        await pg.keyboard.press("Enter")
        t0=time.time()
        for i in range(30):
            await pg.wait_for_timeout(5000)
            txt=await pg.locator("body").inner_text()
            if "137" in txt and "heap" in txt.lower() and time.time()-t0>20: break
        await pg.wait_for_timeout(5000)
        await pg.screenshot(path=OUT+"02-answer.png",full_page=True)
        txt=await pg.locator("main").inner_text() if await pg.locator("main").count() else txt
        open(OUT+"answer.txt","w").write(txt); print("elapsed",round(time.time()-t0),"s; chars",len(txt))
        await b.close()
asyncio.run(main())

/* Optional visual check of the real mascot on a page with restrictive image CSP. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const playwright=require('playwright');
async function main(){
 const browser=await playwright.chromium.launch({headless:true,...(process.env.FLUBBER_TEST_BROWSER?{executablePath:process.env.FLUBBER_TEST_BROWSER}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const page=await browser.newPage({viewport:{width:700,height:500},reducedMotion:'reduce'});
  await page.setContent('<meta http-equiv="Content-Security-Policy" content="img-src \'none\'; style-src \'none\'">');
  const baseline=await page.screenshot();
  const image=fs.readFileSync(path.resolve(__dirname,'../assets/icon-128.png')).toString('base64');
  const source=fs.readFileSync(path.resolve(__dirname,'../../companion/flubber/mascot.js'),'utf8').replace('__FLUBBER_IMAGE__',JSON.stringify(image));
  await page.evaluate(source);
  await page.evaluate(()=>globalThis.__flubberOverlayV2.move(300,220,'click'));
  assert.equal(await page.evaluate(()=>getComputedStyle(document.body).cursor),'none');
  assert.equal(await page.locator('[data-flubber-overlay]').count(),1);
  const visible=await page.screenshot();assert.equal(visible.equals(baseline),false,'mascot must paint visible pixels');
  await page.evaluate(()=>globalThis.__flubberOverlayV2.visible(false));
  assert.equal((await page.screenshot()).equals(baseline),true,'hidden overlay must not appear in model screenshots');
  await page.evaluate(()=>globalThis.__flubberOverlayV2.destroy());
  assert.notEqual(await page.evaluate(()=>getComputedStyle(document.body).cursor),'none');
  assert.equal(await page.locator('[data-flubber-overlay]').count(),0);
  console.log('PASS: mascot paints real pixels under restrictive image CSP, hides the normal page cursor, disappears from model screenshots, and restores the cursor on cleanup.');
 }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});

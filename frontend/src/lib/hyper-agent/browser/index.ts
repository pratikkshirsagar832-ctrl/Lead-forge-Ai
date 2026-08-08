export class BrowserAutomation {
  private browser: any = null
  private context: any = null
  private initialized = false

  async init(): Promise<void> {
    if (this.initialized) return
    const { chromium } = await import('playwright')
    this.browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    })
    this.context = await this.browser.newContext({
      userAgent:
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })
    this.initialized = true
  }

  async getPage(): Promise<any> {
    if (!this.context) await this.init()
    return this.context!.newPage()
  }

  async navigate(url: string): Promise<any> {
    const page = await this.getPage()
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 })
    return page
  }

  async scrape(
    url: string,
    selectors: Record<string, string>
  ): Promise<Record<string, string | string[]>> {
    const page = await this.navigate(url)
    const result: Record<string, string | string[]> = {}
    for (const [key, selector] of Object.entries(selectors)) {
      try {
        const elements = await page.$$(selector)
        if (elements.length === 0) {
          result[key] = ''
        } else if (elements.length === 1) {
          result[key] = (await elements[0].textContent()) || ''
        } else {
          result[key] = await Promise.all(
            elements.map((el: any) => el.textContent() || '')
          )
        }
      } catch {
        result[key] = ''
      }
    }
    await page.close()
    return result
  }

  async screenshot(url: string, _path?: string): Promise<Buffer> {
    const page = await this.navigate(url)
    const screenshot = await page.screenshot({ fullPage: true, type: 'png' })
    await page.close()
    return screenshot
  }

  async extractLinks(
    url: string
  ): Promise<Array<{ text: string; href: string }>> {
    const page = await this.navigate(url)
    const links = await page.$$eval('a[href]', (els: any) =>
      els.map((el: any) => ({
        text: el.innerText.trim(),
        href: el.href,
      }))
    )
    await page.close()
    return links
  }

  async extractText(url: string): Promise<string> {
    const page = await this.navigate(url)
    const text = await page.innerText('body')
    await page.close()
    return text
  }

  async fillForm(
    url: string,
    fields: Record<string, string>,
    submitSelector?: string
  ): Promise<any> {
    const page = await this.navigate(url)
    for (const [selector, value] of Object.entries(fields)) {
      await page.fill(selector, value)
    }
    if (submitSelector) {
      await page.click(submitSelector)
      await page.waitForLoadState('networkidle')
    }
    return page
  }

  async evaluate<T>(url: string, fn: () => T): Promise<T> {
    const page = await this.navigate(url)
    const result = await page.evaluate(fn)
    await page.close()
    return result
  }

  async withPage<T>(url: string, fn: (page: any) => Promise<T>): Promise<T> {
    const page = await this.navigate(url)
    try {
      return await fn(page)
    } finally {
      await page.close()
    }
  }

  async close(): Promise<void> {
    if (this.browser) {
      await this.browser.close()
      this.browser = null
      this.context = null
      this.initialized = false
    }
  }
}

export const browser = new BrowserAutomation()
export default browser

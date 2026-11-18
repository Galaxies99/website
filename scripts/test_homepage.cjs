#!/usr/bin/env node
// Setup: npm install --prefix .cache/browser-tests playwright
// Run against a local server: node scripts/test_homepage.cjs [http://127.0.0.1:8765]
// Uses installed Google Chrome; set PLAYWRIGHT_CHANNEL if another channel is needed.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('../.cache/browser-tests/node_modules/playwright');
const baseURL = process.argv[2] || 'http://127.0.0.1:8765';

(async () => {
  const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const requests = [];
  const errors = [];
  page.on('request', request => requests.push(request.url()));
  page.on('pageerror', error => errors.push(error.message));
  // Keep tests offline apart from the local preview; never send analytics.
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === new URL(baseURL).origin ? route.continue() : route.abort();
  });
  const check = (name) => console.log(`PASS ${name}`);
  const visiblePapers = () => page.locator('#section-publications tr:visible papertitle').count();
  const focusInside = selector => page.evaluate(selector => document.querySelector(selector).contains(document.activeElement), selector);

  try {
    await page.goto(baseURL, { waitUntil: 'load' });
    await page.waitForFunction(() => document.querySelector('#profileImg').complete && document.querySelector('#profileImg').naturalWidth > 0);
    const paperCount = await page.locator('#section-publications papertitle').count();
    const selectedCount = await page.locator('#section-publications .paper-row-selected papertitle').count();
    assert.equal(await visiblePapers(), selectedCount);
    assert.equal(await page.locator('#section-publications tr:not(.paper-row-selected):visible papertitle').count(), 0);
    assert.equal(await page.locator('h1').count(), 1);
    assert.equal(await page.locator('h2.section-title').count(), 6);
    assert.equal(await page.locator('heading, name').count(), 0);
    assert.ok(await page.locator('meta[name=description]').getAttribute('content'));
    assert.equal(await page.locator('link[rel=canonical]').getAttribute('href'), 'https://tonyfang.net/');
    assert.equal(await page.locator('meta[name="twitter:card"]').getAttribute('content'), 'summary_large_image');
    const shareURL = await page.locator('meta[property="og:image"]').getAttribute('content');
    assert.equal((await context.request.get(baseURL + new URL(shareURL).pathname)).status(), 200);
    check('semantic headings, all publications preserved, and sharing metadata');
    assert.equal((await page.locator('#misc-notes-title').textContent()).trim(), '🎓 Teaching');
    assert.deepEqual(await page.locator('.teaching-list > li').evaluateAll(rows => rows.map(row => [
      row.querySelector('.teaching-course').textContent,
      row.querySelector('.teaching-term').textContent,
    ])), [
      ['Linear Algebra (Honor)', 'Fall 2021 & Fall 2022'],
      ['Algorithm and Complexity', 'Spring 2022'],
      ['Mathematical Analysis (Honor)', 'Fall 2020 & Fall 2021'],
      ['C++ Programming Language (Honor)', 'Fall 2020'],
      ['Data Structure (Honor)', 'Spring 2019'],
    ]);
    assert.deepEqual(await page.locator('#section-notes p a').evaluateAll(links => links.map(link => link.href)), [
      'https://tonyfang.net/notes',
      'https://github.com/galaxies99/SJTU-course-notes',
    ]);
    check('five teaching appointments and all semesters are accurate; both course-note links are preserved');
    await page.keyboard.press('Tab');
    assert.ok(await page.locator('.skip-link').evaluate(el => el === document.activeElement));
    await page.keyboard.press('Enter');
    assert.ok(await page.locator('#main-content').evaluate(el => el === document.activeElement));
    check('keyboard skip link moves focus directly to main content');

    const photoRequests = requests.filter(url => /\/profile\d/.test(url));
    assert.equal(photoRequests.length, 1, JSON.stringify(photoRequests));
    assert.match(photoRequests[0], /profile5-240\.webp$/);
    assert.equal(await page.locator('#profileImg').getAttribute('width'), '720');
    check('only the correctly sized initial profile photo is requested');

    const photo = page.getByRole('button', { name: 'Profile photo. Click to change.', exact: true });
    await photo.click();
    await page.waitForFunction(() => document.querySelector('#profileImg').alt.includes('Istanbul'));
    assert.equal(requests.filter(url => /\/profile[23]-/.test(url)).length, 0);
    check('alternative photos load only on interaction');
    await page.route('**/profile2-*.webp', route => route.abort());
    await photo.press('ArrowRight');
    await page.waitForFunction(() => !document.querySelector('#profileImg').hasAttribute('aria-busy'));
    assert.match(await photo.getAttribute('alt'), /Istanbul/);
    await page.unroute('**/profile2-*.webp');
    await photo.press('ArrowRight');
    await page.waitForFunction(() => document.querySelector('#profileImg').alt.includes('Oslo'));
    await photo.press('ArrowLeft');
    await page.waitForFunction(() => document.querySelector('#profileImg').alt.includes('Istanbul'));
    check('photo load failures retain the current image; keyboard cycling recovers');

    const selectedView = page.locator('[data-filter="selected"]');
    const allView = page.locator('[data-filter="show-all"]');
    assert.equal(await selectedView.getAttribute('aria-pressed'), 'true');
    assert.equal(await allView.getAttribute('aria-pressed'), 'false');
    assert.equal(await page.locator('#pubClearFilters').isVisible(), false);
    await allView.click();
    assert.equal(await visiblePapers(), paperCount);
    assert.equal(await allView.getAttribute('aria-pressed'), 'true');
    assert.equal(await selectedView.getAttribute('aria-pressed'), 'false');
    await selectedView.press('Enter');
    assert.equal(await visiblePapers(), selectedCount);
    check('Selected is the default; All reveals every paper and Selected collapses the list again');

    await page.locator('#pubRoleFilter').selectOption('corresponding');
    await page.locator('#pubTopicDropdown summary').click();
    await page.locator('[data-filter="Human Video"]').click();
    assert.equal(await visiblePapers(), 0);
    assert.ok(await page.locator('#publicationsEmpty').isVisible());
    assert.ok(await page.locator('#pubClearFilters').isVisible());
    await page.locator('#publicationsEmpty [data-clear-publication-filters]').click();
    assert.equal(await visiblePapers(), selectedCount);
    assert.equal(await page.locator('#pubRoleFilter').inputValue(), 'all');
    assert.equal(await page.locator('#pubTopicSummary').textContent(), 'All topics');
    assert.equal(await page.locator('#publicationsEmpty').isVisible(), false);
    assert.equal(await page.locator('#pubClearFilters').isVisible(), false);
    assert.ok(await focusInside('.pub-filter-btn-selected'));
    check('empty-state feedback, full reset, and focus after hiding the reset button');

    await page.locator('#pubRoleFilter').selectOption('first');
    await page.locator('#pubTopicDropdown summary').click();
    await page.locator('[data-filter="Imitation Learning"]').click();
    const visibleTitles = page.locator('#section-publications tr:visible papertitle');
    const selectedMatches = await visibleTitles.allTextContents();
    assert.ok(selectedMatches.length > 0 && selectedMatches.length < selectedCount);
    assert.equal(await page.locator('#section-publications tr:not(.paper-row-selected):visible papertitle').count(), 0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#pubTopicDropdown').evaluate(el => el.open), false);
    await allView.click();
    const allMatches = await visibleTitles.allTextContents();
    assert.ok(allMatches.length < paperCount && selectedMatches.every(title => allMatches.includes(title)));
    assert.equal(await page.locator('#pubRoleFilter').inputValue(), 'first');
    assert.equal(await page.locator('#pubTopicSummary').textContent(), 'Imitation Learning');
    await page.locator('#pubClearFilters').click();
    assert.equal(await visiblePapers(), paperCount);
    assert.ok(await focusInside('[data-filter="show-all"]'));
    await selectedView.click();
    check('Topic and authorship filters apply in both views; clearing keeps the current view and restores focus');

    const more = page.locator('#siteNavMore');
    const moreToggle = more.locator('summary');
    const moreLinks = more.locator('a');
    const moreTargets = ['#section-services', '#section-collab', '#section-misc'];
    assert.deepEqual(await moreLinks.evaluateAll(links => links.map(link => link.getAttribute('href'))), moreTargets);
    assert.equal(await more.evaluate(el => el.open), false);
    assert.equal(await moreLinks.first().isVisible(), false);
    await moreToggle.click();
    await moreLinks.first().waitFor({ state: 'visible' });
    await moreToggle.click();
    assert.equal(await more.evaluate(el => el.open), false);
    await moreToggle.press('Enter');
    assert.equal(await more.evaluate(el => el.open), true);
    await page.keyboard.press('Tab');
    assert.ok(await moreLinks.first().evaluate(el => el === document.activeElement));
    await page.keyboard.press('Escape');
    assert.equal(await more.evaluate(el => el.open), false);
    assert.ok(await moreToggle.evaluate(el => el === document.activeElement));
    await moreToggle.press('Space');
    assert.equal(await more.evaluate(el => el.open), true);
    for (let i = 0; i < 4; i++) await page.keyboard.press('Tab');
    assert.ok(await page.locator('#themeToggle').evaluate(el => el === document.activeElement));
    assert.equal(await more.evaluate(el => el.open), false);
    await moreToggle.press('Enter');
    await page.keyboard.press('Shift+Tab');
    assert.ok(await page.locator('#siteNavLinks a').last().evaluate(el => el === document.activeElement));
    assert.equal(await more.evaluate(el => el.open), false);
    await moreToggle.click();
    await page.locator('.profile-intro').click();
    assert.equal(await more.evaluate(el => el.open), false);
    check('More supports click, Enter, Space, Tab, Shift+Tab, Escape, and outside dismissal');

    for (const target of moreTargets) {
      await moreToggle.click();
      await more.locator(`a[href="${target}"]`).press('Enter');
      assert.equal(await more.evaluate(el => el.open), false);
      assert.equal(new URL(page.url()).hash, target);
      assert.ok(await page.locator(target).evaluate(el => el === document.activeElement));
      await page.waitForFunction(target => {
        const top = document.querySelector(target).getBoundingClientRect().top;
        return top >= document.querySelector('.site-nav').getBoundingClientRect().bottom && top <= 81;
      }, target);
    }
    check('all three More links navigate below the sticky header and focus their destination');

    async function testDialog(trigger, selector) {
      await trigger.scrollIntoViewIfNeeded();
      const before = await page.locator('#top').evaluate(el => el.getBoundingClientRect().left);
      await trigger.click();
      const dialog = page.locator(selector);
      await dialog.waitFor({ state: 'visible' });
      assert.ok(await focusInside(selector));
      assert.equal(await page.locator('#main-content').evaluate(el => el.inert), true);
      assert.equal(await dialog.getAttribute('aria-modal'), 'true');
      assert.equal(await page.locator('#top').evaluate(el => el.getBoundingClientRect().left), before);
      await page.keyboard.press('Shift+Tab');
      assert.ok(await focusInside(selector));
      await page.keyboard.press('Tab');
      assert.ok(await focusInside(selector));
      for (let i = 0; i < 5; i++) {
        await page.keyboard.press('Tab');
        assert.ok(await focusInside(selector));
      }
      await page.keyboard.press('Escape');
      assert.equal(await dialog.isVisible(), false);
      assert.equal(await page.locator('#main-content').evaluate(el => el.inert), false);
      assert.ok(await trigger.evaluate(el => el === document.activeElement));
      check(`${selector}: focus trap, Escape, restoration, and stationary background`);
    }
    await testDialog(page.locator('[data-modal=email]'), '#emailModal');
    await testDialog(page.locator('[data-modal=wechat]'), '#wechatModal');
    await testDialog(page.locator('#namePronunciationLink'), '#pronunciationModal');
    await page.locator('.travel-view-btn[data-view=cards]').click();
    await testDialog(page.locator('.travel-card').first(), '#travelModal');

    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await page.locator('.paper-honor').first().evaluate(el => getComputedStyle(el, '::after').animationName), 'none');
    assert.equal(await photo.evaluate(el => getComputedStyle(el).transitionDuration), '0s');
    check('honor badges are static and profile transitions respect reduced motion');

    for (const width of [320, 375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => {
          if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
          else document.documentElement.removeAttribute('data-theme');
        }, theme);
        const metrics = await page.evaluate(() => ({
          width: innerWidth,
          scroll: document.documentElement.scrollWidth,
          sizes: ['.name-en', '.name-cn'].map(s => getComputedStyle(document.querySelector(s)).fontSize),
        }));
        assert.ok(metrics.scroll <= metrics.width, `${width}px ${theme}: horizontal overflow ${metrics.scroll}`);
        assert.equal(metrics.sizes[0], metrics.sizes[1]);
        const navBefore = await page.locator('.site-nav').boundingBox();
        await moreToggle.click();
        await moreLinks.first().waitFor({ state: 'visible' });
        const morePanel = await page.locator('#siteNavMoreLinks').boundingBox();
        const navAfter = await page.locator('.site-nav').boundingBox();
        assert.equal(navAfter.height, navBefore.height, 'Opening More must not shift the page');
        assert.ok(morePanel.x >= 0 && morePanel.x + morePanel.width <= width, `${width}px: More panel outside viewport`);
        assert.ok(await moreLinks.evaluateAll(links => links.every(link => {
          const rect = link.getBoundingClientRect();
          return link.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
        })), 'More links must not be clipped or covered');
        if (width === 375 || width === 1280) {
          await page.screenshot({ path: path.join(__dirname, `../.cache/homepage-more-${width}-${theme}.png`) });
        }
        if (width <= 640) {
          const shortTargets = await page.locator('.profile-link, .paper-links a:visible, .publications-view button, #pubTopicDropdown summary, #pubRoleFilter, .theme-toggle, .site-nav-links a, .site-nav-more summary, .site-nav-more-links a').evaluateAll(elements =>
            elements.filter(el => el.getBoundingClientRect().height < 44).map(el => el.outerHTML));
          assert.deepEqual(shortTargets, []);
        }
        await page.keyboard.press('Escape');
        if (width <= 640) {
          await page.locator('#pubTopicDropdown summary').click();
          const dropdown = await page.locator('#pubTopicDropdown .publications-filter-buttons').boundingBox();
          assert.ok(dropdown.x >= 0 && dropdown.x + dropdown.width <= width);
          await page.keyboard.press('Escape');
        }
        assert.ok(await page.locator('.teaching-list > li').evaluateAll((rows, width) => rows.every(row => {
          const course = row.querySelector('.teaching-course').getBoundingClientRect();
          const term = row.querySelector('.teaching-term').getBoundingClientRect();
          return width <= 640 ? course.bottom <= term.top : course.right <= term.left;
        }), width), `${width}px: teaching courses and semesters must not overlap`);
        if (width === 375 || width === 1280) {
          await page.locator('#section-notes').scrollIntoViewIfNeeded();
          await page.screenshot({ path: path.join(__dirname, `../.cache/homepage-teaching-${width}-${theme}.png`) });
        }
        check(`${width}px ${theme}: no overflow, unclipped More panel, consistent name sizes, mobile targets, readable teaching list`);
      }
    }

    await page.setViewportSize({ width: 375, height: 812 });
    await page.locator('#siteNavLinks').evaluate(el => { el.scrollLeft = 0; });
    await page.waitForFunction(() => {
      const links = document.querySelector('#siteNavLinks');
      return links.parentElement.classList.contains('has-overflow-end') === (links.scrollWidth - links.clientWidth > 2);
    });
    // More is shorter than Miscellaneous; only narrower screens need scrolling now.
    await page.setViewportSize({ width: 320, height: 812 });
    await page.locator('#siteNavLinks').evaluate(el => { el.scrollLeft = 0; });
    await page.waitForFunction(() => document.querySelector('.site-nav-scroll').classList.contains('has-overflow-end'));
    await page.locator('#siteNavLinks').evaluate(el => { el.scrollLeft = el.scrollWidth; });
    await page.waitForFunction(() => document.querySelector('.site-nav-scroll').classList.contains('has-overflow-start') && !document.querySelector('.site-nav-scroll').classList.contains('has-overflow-end'));
    check('navigation scroll hints match actual overflow and update at both ends');
    await page.setViewportSize({ width: 375, height: 812 });
    await testDialog(page.locator('[data-modal=email]'), '#emailModal');

    await page.locator('.publications-heading-row').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(__dirname, '../.cache/homepage-mobile.png') });
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.evaluate(() => document.documentElement.removeAttribute('data-theme'));
    await page.locator('.profile-name-row').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(__dirname, '../.cache/homepage-desktop.png') });
    assert.deepEqual(errors, [], `JavaScript errors: ${errors.join('; ')}`);
    check('no uncaught JavaScript errors');

    for (const javaScriptEnabled of [true, false]) {
      const mobile = await browser.newContext({
        viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, javaScriptEnabled,
      });
      const mobilePage = await mobile.newPage();
      await mobilePage.route('**/*', route => new URL(route.request().url()).origin === new URL(baseURL).origin
        ? route.continue() : route.abort());
      await mobilePage.goto(baseURL, { waitUntil: 'load' });
      const mobileMore = mobilePage.locator('#siteNavMore');
      await mobileMore.locator('summary').tap();
      await mobileMore.locator('a[href="#section-collab"]').tap();
      assert.equal(new URL(mobilePage.url()).hash, '#section-collab');
      if (javaScriptEnabled) assert.equal(await mobileMore.getAttribute('open'), null);
      await mobile.close();
      check(`touch navigation ${javaScriptEnabled ? 'with' : 'without'} JavaScript`);
    }

    for (const [scale, width, expected] of [[2, 1280, 480], [3, 375, 720]]) {
      const retina = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: scale });
      const retinaPage = await retina.newPage();
      const photos = [];
      retinaPage.on('request', request => {
        if (/\/profile\d/.test(request.url())) photos.push(request.url());
      });
      await retinaPage.route('**/*', route => new URL(route.request().url()).origin === new URL(baseURL).origin
        ? route.continue() : route.abort());
      await retinaPage.goto(baseURL, { waitUntil: 'load' });
      await retinaPage.waitForFunction(() => document.querySelector('#profileImg').complete && document.querySelector('#profileImg').naturalWidth > 0);
      assert.equal(photos.length, 1);
      assert.ok(photos[0].endsWith(`profile5-${expected}.webp`), photos[0]);
      await retina.close();
      check(`${scale}x display: only the ${expected}px profile variant is loaded`);
    }
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});

#!/usr/bin/env node
// Setup: npm install --prefix .cache/browser-tests playwright
// Run against a local server: node scripts/test_homepage.cjs [http://127.0.0.1:8765]
// Run the Scholar and GitHub updaters first so homepage counts match their data snapshots.
// Uses installed Google Chrome; set PLAYWRIGHT_CHANNEL if another channel is needed.
const assert = require('node:assert/strict');
const path = require('node:path');
const scholarStats = require('../data/scholar-stats.json');
const githubStars = require('../data/github-stars.json');
const { chromium } = require('../.cache/browser-tests/node_modules/playwright');
const baseURL = process.argv[2] || 'http://127.0.0.1:8765';

// Derive identity from each original href, independently of generated badge data.
function githubRepositoryKey(href) {
  let url;
  try { url = new URL(href); } catch { return null; }
  if (!['http:', 'https:'].includes(url.protocol) || !['github.com', 'www.github.com'].includes(url.hostname.toLowerCase())) return null;
  const [owner, rawRepo] = url.pathname.split('/').filter(Boolean);
  const repo = rawRepo?.replace(/\.git$/i, '');
  return owner && repo ? `${owner}/${repo}`.toLowerCase() : null;
}

// Homepage order and stable Scholar IDs are independent of Scholar title changes.
const expectedPapers = [
  ['FlexWAM:', null],
  ['FP2:', 'hFOr9nPyWt4C'],
  ['Rethinking Visual Embodiment Dependence', '-f6ydRqryjwC'],
  ['HINT:', 'hC7cP41nSMkC'],
  ['MATE:', 'ZeXyd9-uunAC'],
  ['AnyDexRT:', 'mB3voiENLucC'],
  ['Force Policy:', '4DMP91E08xMC'],
  ['ChronoFlow Policy:', '7PzlFSSx8tAC'],
  ['LIDEA:', 'mVmsd5A6BfQC'],
  ['X-Imitator:', 'QIV2ME_5wuYC'],
  ['History-Aware Visuomotor Policy Learning via Point Tracking', 'qxL8FJ1GzNcC'],
  ['Learning Dexterous Manipulation with Quantized Hand State', 'aqlVkmm33-oC'],
  ['AnyDexGrasp:', 'Zph67rFs4hoC'],
  ['AirExo-2:', 'ULOm3_A8WrAC'],
  ['Knowledge-Driven Imitation Learning:', 'M3ejUd6NZC8C'],
  ['SIME:', '4TOpqqG69KYC'],
  ['Dense Policy:', '_kc_bZDykSQC'],
  ['FoAR:', '3fE2CSJIrl8C'],
  ['Motion Before Action:', 'MXK_kJrjxJIC'],
  ['CAGE:', '8k81kl-MbHgC'],
  ['Towards Effective Utilization of Mixed-Quality Demonstrations', '5nxA0vEk-isC'],
  ['RISE:', 'hqOjcs7Dif8C'],
  ['Open X-Embodiment:', 'roLk4NBRz8UC'],
  ['AirExo:', 'eQOLeE2rZwMC'],
  ['RH20T:', 'LkGwnXOMwfcC'],
  ['Flexible Handover', 'YsMSGLbcyi4C'],
  ['Target-Referenced Reactive Grasping', 'Y0pCki6q_DkC'],
  ['AnyGrasp:', 'zYLM7Y9cAGgC'],
  ['TransCG:', '2osOgNQ5qMEC'],
  ['Graspness Discovery', 'd1gkVwhDpl0C'],
];

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
  const visibleCitations = () => page.locator('#section-publications .paper-venue a.paper-citations:visible').count();
  const focusInside = selector => page.evaluate(selector => document.querySelector(selector).contains(document.activeElement), selector);
  const starBadges = page.locator('#section-publications .paper-links a > .github-stars');
  async function assertVisibleGithubStars() {
    const hrefs = await page.locator('#section-publications .paper-links a:visible').evaluateAll(links => links.map(link => link.getAttribute('href')));
    const expected = hrefs.filter(href => githubRepositoryKey(href)).length;
    assert.equal(await page.locator('#section-publications .paper-links a > .github-stars:visible').count(), expected, 'Visible star counts follow publication view and filters');
  }

  try {
    await page.goto(baseURL, { waitUntil: 'load' });
    await page.waitForFunction(() => document.querySelector('#profileImg').complete && document.querySelector('#profileImg').naturalWidth > 0);
    const paperCount = await page.locator('#section-publications papertitle').count();
    const selectedCount = await page.locator('#section-publications .paper-row-selected papertitle').count();
    const citationCount = expectedPapers.filter(([, id]) => id !== null).length;
    assert.equal(paperCount, expectedPapers.length);
    assert.equal(await visiblePapers(), selectedCount);
    assert.equal(await page.locator('#section-publications tr:not(.paper-row-selected):visible papertitle').count(), 0);
    const flexwam = page.locator('#section-publications tr').filter({ has: page.locator('papertitle', { hasText: 'FlexWAM:' }) });
    assert.equal(await flexwam.count(), 1);
    assert.equal(await flexwam.isVisible(), false, 'FlexWAM must not appear in Selected');
    const openXEmbodiment = page.locator('#section-publications tr').filter({ has: page.locator('papertitle', { hasText: 'Open X-Embodiment:' }) });
    assert.equal(await openXEmbodiment.count(), 1);
    assert.ok(await openXEmbodiment.evaluate(row => row.classList.contains('paper-row-selected')), 'Open X-Embodiment must be Selected');
    assert.ok(await openXEmbodiment.isVisible(), 'Open X-Embodiment must appear in the default Selected view');
    const citationLinks = page.locator('#section-publications .paper-venue a.paper-citations');
    assert.equal(await citationLinks.count(), citationCount, 'Run the Scholar updater before this browser suite');
    assert.equal(await visibleCitations(), selectedCount);
    await assertVisibleGithubStars();
    assert.equal(await page.locator('a.paper-citations').count(), citationCount, 'Citations belong only to publication venue rows');
    assert.equal(await page.locator('.paper-links .paper-citations, .paper-link-citations').count(), 0, 'Citations must not remain standalone paper-link buttons');
    assert.ok(await openXEmbodiment.locator('.paper-venue a.paper-citations').isVisible());
    assert.equal(await page.locator('#section-projects').count(), 0, 'Commented projects must remain inactive');
    const projectComments = await page.evaluate(() => {
      const walker = document.createTreeWalker(document, NodeFilter.SHOW_COMMENT);
      const comments = [];
      while (walker.nextNode()) {
        if (walker.currentNode.data.includes('Selected Projects is retained')) comments.push(walker.currentNode.data);
      }
      return comments;
    });
    assert.equal(projectComments.length, 1);
    assert.match(projectComments[0], /EasyRobot/);
    assert.match(projectComments[0], /Oh-My-Papers/);
    assert.doesNotMatch(projectComments[0], /paper-citations|paper-link-citations/);
    assert.doesNotMatch(projectComments[0], /github-stars/);
    assert.equal(githubStars.version, 1);
    assert.ok(githubStars.repositories && typeof githubStars.repositories === 'object');
    const repositoryLinks = await page.locator('#section-publications .paper-links a').evaluateAll(links => links.map(link => {
      const originalLabel = link.cloneNode(true);
      originalLabel.querySelectorAll('.github-stars').forEach(badge => badge.remove());
      return {
        href: link.getAttribute('href'),
        title: link.closest('tr').querySelector('papertitle').textContent.trim(),
        label: originalLabel.textContent.trim(),
        badges: [...link.querySelectorAll('.github-stars')].map(badge => ({
          key: badge.dataset.githubRepo,
          count: badge.querySelector('.github-stars-count')?.textContent,
          countElements: badge.querySelectorAll('.github-stars-count').length,
          tooltip: badge.title,
          label: badge.querySelector('.github-stars-label')?.textContent,
          labelElements: badge.querySelectorAll('.github-stars-label').length,
          star: badge.querySelector('[aria-hidden="true"]')?.textContent,
          isDirectSpan: badge.tagName === 'SPAN' && badge.parentElement === link,
          interactiveChildren: badge.querySelectorAll('a, button, input, [tabindex]').length,
          startMarker: badge.previousSibling?.nodeType === Node.COMMENT_NODE ? badge.previousSibling.data.trim() : null,
          endMarker: badge.nextSibling?.nodeType === Node.COMMENT_NODE ? badge.nextSibling.data.trim() : null,
        })),
      };
    }));
    const eligibleRepositoryLinks = repositoryLinks.filter(link => githubRepositoryKey(link.href));
    assert.ok(eligibleRepositoryLinks.length > 0, 'Publication repository links must remain present');
    for (const link of repositoryLinks) {
      const key = githubRepositoryKey(link.href);
      assert.equal(link.badges.length, key ? 1 : 0, `${link.title}: exactly one badge per eligible repository link (${link.href})`);
      if (!key) continue;
      const badge = link.badges[0];
      assert.equal(badge.key, key, `${link.href}: repository key comes from the original URL`);
      assert.ok(badge.isDirectSpan, `${key}: badge belongs inside the existing anchor`);
      assert.equal(badge.interactiveChildren, 0, `${key}: badge must not create a nested click target`);
      assert.equal(badge.startMarker, 'github-stars:start');
      assert.equal(badge.endMarker, 'github-stars:end');
      assert.equal(badge.countElements, 1);
      assert.equal(badge.labelElements, 1);
      assert.equal(badge.star, '★');
      const snapshot = githubStars.repositories[key];
      let count = '—';
      let tooltip = `GitHub · ${key} · Star count not available yet`;
      let label = ' GitHub stars unavailable';
      if (snapshot?.stars != null) {
        assert.ok(Number.isInteger(snapshot.stars) && snapshot.stars >= 0, `${key}: invalid snapshot count`);
        assert.ok(typeof snapshot.full_name === 'string' && snapshot.full_name.includes('/'), `${key}: missing canonical repository name`);
        count = snapshot.stars.toLocaleString('en-US');
        const updated = new Date(snapshot.updated_at).toISOString().slice(0, 16).replace('T', ' ');
        tooltip = `GitHub · ${snapshot.full_name} · Updated ${updated} UTC`;
        label = ' GitHub stars';
      }
      assert.equal(badge.count, count, `${key}: snapshot star count (unknown is a dash, zero is 0)`);
      assert.equal(badge.tooltip, tooltip, `${key}: source, repository, and per-repository update time`);
      assert.equal(badge.label, label, `${key}: accessible count meaning`);
    }
    assert.equal(await starBadges.count(), eligibleRepositoryLinks.length, 'Every eligible anchor has exactly one direct badge');
    assert.equal(await page.locator('.github-stars').count(), eligibleRepositoryLinks.length, 'Authors, profile links, non-GitHub links, and other sections must not receive star badges');
    const airexoLinks = eligibleRepositoryLinks.filter(link => link.title.startsWith('AirExo-2:'));
    assert.deepEqual(airexoLinks.map(link => [githubRepositoryKey(link.href), link.label]), [
      ['airexo/airexo-2', 'data collection code'],
      ['rise-policy/rise-2', 'policy code'],
    ], 'AirExo-2 retains both distinct repository links and original labels');
    await assertVisibleGithubStars();
    check('repository star badges match their snapshot, original URLs, labels, accessible text, and update dates; unrelated links stay unchanged');
    assert.equal(scholarStats.scholar_id, 'Kyio_RAAAAAJ');
    const paperRows = await page.locator('#section-publications tr').filter({ has: page.locator('papertitle') }).evaluateAll(rows => rows.map(row => ({
      title: row.querySelector('papertitle').textContent.trim(),
      citations: [...row.querySelectorAll('.paper-venue a.paper-citations')].map(link => ({
        id: link.dataset.scholarId,
        href: link.href,
        text: link.textContent.trim(),
        tooltip: link.title,
        label: link.getAttribute('aria-label'),
        isLast: link.parentElement.matches('.paper-venue') && link.parentElement.lastElementChild === link,
        followsVenueAndHonors: !!link.parentElement.querySelector('em') && [...link.parentElement.querySelectorAll('em, .paper-honor')]
          .every(venue => !!(venue.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING)),
        startMarker: link.previousSibling?.nodeType === Node.COMMENT_NODE ? link.previousSibling.data : null,
        endMarker: link.nextSibling?.nodeType === Node.COMMENT_NODE ? link.nextSibling.data : null,
      })),
    })));
    assert.equal(paperRows.length, paperCount);
    const citationIds = new Set();
    for (const [index, row] of paperRows.entries()) {
      const [titlePrefix, id] = expectedPapers[index];
      assert.ok(row.title.startsWith(titlePrefix), `Publication order/title changed: ${row.title}`);
      if (id === null) {
        assert.equal(row.citations.length, 0, `${row.title}: no verified Scholar ID`);
        continue;
      }
      assert.equal(row.citations.length, 1, row.title);
      const citation = row.citations[0];
      assert.equal(citation.id, id, row.title);
      assert.ok(!citationIds.has(id), `Duplicate citation ID: ${id}`);
      citationIds.add(id);
      assert.ok(citation.isLast && citation.followsVenueAndHonors, `${row.title}: citation belongs after the existing venue and honor labels`);
      assert.equal(citation.startMarker, ` paper-citations:${id}:start `);
      assert.equal(citation.endMarker, ` paper-citations:${id}:end `);
      const url = new URL(citation.href);
      assert.equal(url.origin, 'https://scholar.google.com');
      assert.equal(url.pathname, '/citations');
      assert.equal(url.searchParams.get('view_op'), 'view_citation');
      assert.equal(url.searchParams.get('user'), scholarStats.scholar_id);
      assert.equal(url.searchParams.get('citation_for_view'), `${scholarStats.scholar_id}:${id}`);
      const paper = scholarStats.papers?.[id];
      let text = '—';
      let accessibleCount = 'Citations unavailable';
      let tooltip = 'Google Scholar · Citation count not available yet';
      if (paper) {
        assert.ok(Number.isInteger(paper.citations) && paper.citations >= 0, `${id}: invalid snapshot count`);
        text = paper.citations.toLocaleString('en-US');
        accessibleCount = `${text} ${paper.citations === 1 ? 'citation' : 'citations'}`;
        const updated = new Date(paper.updated_at).toISOString().slice(0, 16).replace('T', ' ');
        tooltip = `Google Scholar · Updated ${updated} UTC`;
      }
      assert.equal(citation.text, text, `${row.title}: numeric-only snapshot citation count`);
      assert.equal(citation.tooltip, tooltip, `${row.title}: per-paper update date`);
      assert.equal(citation.label, `${accessibleCount}. ${tooltip}`, `${row.title}: full accessible citation label`);
    }
    assert.equal(paperRows.find(row => row.citations[0]?.id === 'hC7cP41nSMkC').title,
      'HINT: Human-Intent Inception for Agentic Robot Manipulation');
    check('mapped papers have one numeric Scholar citation after venue/honors; papers without a verified ID have none');
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
    assert.ok(await flexwam.isVisible(), 'All must reveal FlexWAM');
    assert.equal(await visibleCitations(), citationCount, 'All must reveal every citation');
    await assertVisibleGithubStars();
    assert.equal(await allView.getAttribute('aria-pressed'), 'true');
    assert.equal(await selectedView.getAttribute('aria-pressed'), 'false');
    await citationLinks.first().focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    assert.ok(await citationLinks.first().evaluate(el => el === document.activeElement));
    const citationFocus = await citationLinks.first().evaluate(el => ({
      visible: el.matches(':focus-visible'),
      style: getComputedStyle(el).outlineStyle,
      width: parseFloat(getComputedStyle(el).outlineWidth),
    }));
    assert.ok(citationFocus.visible && citationFocus.style === 'solid' && citationFocus.width >= 2);
    await page.keyboard.press('Tab');
    assert.ok(await citationLinks.first().evaluate(link => link.closest('tr').querySelector('papertitle a') === document.activeElement),
      'Venue citation precedes the publication title and paper links in keyboard order');
    const firstRepositoryLink = page.locator('#section-publications .paper-links a:has(.github-stars)').first();
    await firstRepositoryLink.focus();
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    const repositoryFocus = await firstRepositoryLink.evaluate(el => ({
      active: el === document.activeElement,
      visible: el.matches(':focus-visible'),
      style: getComputedStyle(el).outlineStyle,
      width: parseFloat(getComputedStyle(el).outlineWidth),
    }));
    assert.ok(repositoryFocus.active && repositoryFocus.visible && repositoryFocus.style === 'solid' && repositoryFocus.width >= 2,
      'Repository links retain a visible keyboard focus outline with their inline star badge');
    await selectedView.press('Enter');
    assert.equal(await visiblePapers(), selectedCount);
    assert.equal(await visibleCitations(), selectedCount);
    await assertVisibleGithubStars();
    check('Selected remains the default; All reveals every paper and citation; citation links support visible keyboard focus');

    await page.locator('#pubRoleFilter').selectOption('corresponding');
    await page.locator('#pubTopicDropdown summary').click();
    await page.locator('[data-filter="Human Video"]').click();
    assert.equal(await visiblePapers(), 0);
    assert.equal(await visibleCitations(), 0);
    await assertVisibleGithubStars();
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
    assert.equal(await visibleCitations(), selectedMatches.length);
    await assertVisibleGithubStars();
    assert.ok(selectedMatches.length > 0 && selectedMatches.length < selectedCount);
    assert.equal(await page.locator('#section-publications tr:not(.paper-row-selected):visible papertitle').count(), 0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#pubTopicDropdown').evaluate(el => el.open), false);
    await allView.click();
    const allMatches = await visibleTitles.allTextContents();
    assert.equal(await visibleCitations(), allMatches.length);
    await assertVisibleGithubStars();
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

    // Exercise every citation row, including non-selected papers and long link lists.
    await allView.click();
    assert.equal(await visibleCitations(), citationCount);
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
        assert.equal(await visibleCitations(), citationCount);
        const citationLayoutIssues = await citationLinks.evaluateAll(links => links.flatMap(link => {
          const rect = link.getBoundingClientRect();
          const container = link.parentElement.getBoundingClientRect();
          const style = getComputedStyle(link);
          const icon = getComputedStyle(link, '::before');
          const issues = [];
          if (rect.left < 0 || rect.right > innerWidth || rect.left < container.left - 1 || rect.right > container.right + 1
            || rect.top < container.top - 1 || rect.bottom > container.bottom + 1) issues.push('outside venue row');
          if (link.scrollWidth > link.clientWidth) issues.push('clipped count');
          // Flex children compute inline-flex as flex while staying beside their siblings.
          if (style.display !== 'flex' || style.whiteSpace !== 'nowrap' || !style.fontVariantNumeric.includes('tabular-nums')) issues.push('missing inline citation typography');
          if (style.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(style.borderTopWidth) !== 0 || style.boxShadow !== 'none') issues.push('citation must stay borderless without a visible box');
          if (icon.maskImage === 'none' || parseFloat(icon.width) <= 0) issues.push('missing citation quotation icon');
          for (const sibling of link.parentElement.children) {
            if (sibling === link) continue;
            const other = sibling.getBoundingClientRect();
            if (Math.min(rect.right, other.right) - Math.max(rect.left, other.left) > 1
              && Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top) > 1) issues.push('citation overlaps venue or honor');
          }
          if (innerWidth <= 640 && (rect.height < 24 || rect.width < 24)) issues.push('citation touch target below 24px');
          return issues.map(issue => `${link.dataset.scholarId}: ${issue}`);
        }));
        assert.deepEqual(citationLayoutIssues, [], `${width}px ${theme}: citation layout`);
        await assertVisibleGithubStars();
        const starLayoutIssues = await starBadges.evaluateAll(badges => badges.flatMap(badge => {
          const issues = [];
          const rect = badge.getBoundingClientRect();
          const link = badge.parentElement;
          const control = link.getBoundingClientRect();
          const style = getComputedStyle(badge);
          const count = badge.querySelector('.github-stars-count');
          const star = badge.querySelector('[aria-hidden="true"]');
          const label = badge.querySelector('.github-stars-label');
          const labelStyle = getComputedStyle(label);
          const labelRect = label.getBoundingClientRect();
          const overlaps = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
            && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;
          if (rect.left < control.left - 1 || rect.right > control.right + 1 || rect.top < control.top - 1 || rect.bottom > control.bottom + 1) issues.push('badge outside its anchor');
          if (badge.scrollWidth > badge.clientWidth + 1) issues.push('clipped badge');
          if (style.display !== 'flex' || style.whiteSpace !== 'nowrap' || !style.fontVariantNumeric.includes('tabular-nums')) issues.push('missing compact count typography');
          if (overlaps(star.getBoundingClientRect(), count.getBoundingClientRect())) issues.push('star overlaps count');
          for (const child of link.childNodes) {
            if (child.nodeType !== Node.TEXT_NODE || !child.textContent.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(child);
            if ([...range.getClientRects()].some(textRect => overlaps(textRect, rect))) issues.push('badge overlaps original link label');
          }
          if (labelStyle.position !== 'absolute' || labelRect.width > 1 || labelRect.height > 1 || labelStyle.clipPath === 'none') issues.push('accessible label must be visually hidden');
          if (labelStyle.display === 'none' || labelStyle.visibility !== 'visible' || label.closest('[aria-hidden="true"], [hidden]')) issues.push('count meaning hidden from screen readers');
          return issues.map(issue => `${badge.dataset.githubRepo}: ${issue}`);
        }));
        assert.deepEqual(starLayoutIssues, [], `${width}px ${theme}: inline GitHub star layout and accessible labels`);
        const controlLayoutIssues = await page.locator('#section-publications .paper-links').evaluateAll(rows => rows.flatMap(row => {
          const container = row.getBoundingClientRect();
          const links = [...row.querySelectorAll('a')];
          return links.flatMap((link, index) => {
            const rect = link.getBoundingClientRect();
            const issues = [];
            if (rect.left < -1 || rect.right > innerWidth + 1 || rect.left < container.left - 1 || rect.right > container.right + 1) issues.push('anchor outside link row');
            if (link.scrollWidth > link.clientWidth + 1) issues.push('anchor content clipped');
            for (const sibling of links.slice(index + 1)) {
              const other = sibling.getBoundingClientRect();
              if (Math.min(rect.right, other.right) - Math.max(rect.left, other.left) > 1
                && Math.min(rect.bottom, other.bottom) - Math.max(rect.top, other.top) > 1) issues.push('overlapping paper links');
            }
            return issues.map(issue => `${link.getAttribute('href')}: ${issue}`);
          });
        }));
        assert.deepEqual(controlLayoutIssues, [], `${width}px ${theme}: repository anchors and sibling controls neither overflow nor overlap`);
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
          const shortTargets = await page.locator('.theme-toggle, .site-nav-links a, .site-nav-more summary, .site-nav-more-links a').evaluateAll(elements =>
            elements.filter(el => el.getBoundingClientRect().height < 44).map(el => el.outerHTML));
          assert.deepEqual(shortTargets, []);
          const compactTargets = await page.locator('.profile-link, .publications-view button, #pubTopicDropdown summary, #pubRoleFilter, .paper-links a:visible').evaluateAll(elements =>
            elements.filter(el => Math.abs(el.getBoundingClientRect().height - 30) > 1).map(el => el.outerHTML));
          assert.deepEqual(compactTargets, [], 'Mobile content controls share a compact 30px height');
          const publicationTargets = await page.locator('.paper-links a:visible, .paper-venue a.paper-citations:visible, .publications-view button, #pubTopicDropdown summary, #pubRoleFilter').evaluateAll(elements =>
            elements.filter(el => el.getBoundingClientRect().height < 24).map(el => el.outerHTML));
          assert.deepEqual(publicationTargets, []);
          const viewBounds = await page.locator('.publications-view').boundingBox();
          assert.ok(viewBounds.width < 220 && viewBounds.height <= 31, 'Mobile publication tabs must stay compact');
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
          for (const id of ['hFOr9nPyWt4C', 'hC7cP41nSMkC', 'ULOm3_A8WrAC', 'roLk4NBRz8UC']) {
            const venue = page.locator('#section-publications .paper-venue').filter({ has: page.locator(`[data-scholar-id="${id}"]`) });
            await venue.screenshot({ path: path.join(__dirname, `../.cache/homepage-citations-${id}-${width}-${theme}.png`) });
          }
          for (const [name, title] of [['hint', 'HINT:'], ['airexo-2', 'AirExo-2:']]) {
            const links = page.locator('#section-publications tr').filter({ has: page.locator('papertitle', { hasText: title }) }).locator('.paper-links');
            await links.screenshot({ path: path.join(__dirname, `../.cache/homepage-github-stars-${name}-${width}-${theme}.png`) });
          }
        }
        check(`${width}px ${theme}: no overflow or overlapping star badges and paper links, unclipped More panel and citations, consistent name sizes, mobile targets, readable teaching list`);
      }
    }
    await selectedView.click();
    assert.equal(await visiblePapers(), selectedCount);
    assert.equal(await visibleCitations(), selectedCount);
    await assertVisibleGithubStars();
    assert.ok(await openXEmbodiment.isVisible(), 'Returning to Selected keeps Open X-Embodiment visible');

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

    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.locator('.site-nav-links a[href="#top"]').click();
    await page.waitForFunction(() => document.querySelector('.profile-stage').classList.contains('hero-in-view'));
    await page.mouse.move(800, 200);
    await page.waitForFunction(() => document.querySelector('.profile-stage').style.getPropertyValue('--portrait-y') !== '');
    await page.mouse.move(0, 0);
    await page.waitForFunction(() => document.querySelector('.profile-stage').style.getPropertyValue('--portrait-y') === '');

    // Rotating transparent corners must not widen the page between breakpoints.
    for (const width of [375, 641, 662, 768]) {
      await page.setViewportSize({ width, height: 900 });
      const overflow = await page.locator('.portrait-orbit').evaluate(el => {
        const animation = el.getAnimations()[0];
        animation.pause();
        const widths = [];
        for (const time of [0, 3000, 6000, 9000, 12000, 15000, 18000, 21000]) {
          animation.currentTime = time;
          widths.push(document.documentElement.scrollWidth);
        }
        animation.play();
        return Math.max(...widths) - window.innerWidth;
      });
      assert.ok(overflow <= 0, `${width}px: orbit causes ${overflow}px horizontal overflow`);
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    for (const target of ['#section-services', '#section-talks']) {
      await page.locator(target).evaluate(el => el.scrollIntoView({ behavior: 'instant' }));
      await page.waitForFunction(target => document.querySelector('.site-nav [aria-current="location"]')?.getAttribute('href') === target, target);
    }
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.portrait-orbit')).animationPlayState === 'paused');
    assert.ok(Number(await page.locator('.site-nav').evaluate(el => el.style.getPropertyValue('--reading-progress'))) > 0);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await page.locator('.portrait-orbit').evaluate(el => getComputedStyle(el).animationName), 'none');
    assert.equal(await page.locator('.profile-portrait').evaluate(el => getComputedStyle(el).transitionDuration), '0s');
    check('pointer feedback resets, orbit stays within narrow viewports, navigation follows document order, and offscreen/reduced motion stops animation');

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
      if (javaScriptEnabled) await mobilePage.emulateMedia({ reducedMotion: 'reduce' });
      const identity = await mobilePage.locator('#profileImg').boundingBox();
      const name = await mobilePage.locator('.profile-name-row').boundingBox();
      const contact = await mobilePage.locator('.profile-links').boundingBox();
      const intro = await mobilePage.locator('.profile-intro').boundingBox();
      assert.ok(identity.y < 240 && name.y < 240, 'Mobile identity must be visible near the top');
      assert.ok(contact.y + contact.height < 600 && contact.y + contact.height <= intro.y, 'Contact links precede the biography on mobile');
      const firstPaper = mobilePage.locator('#section-publications tr:visible').filter({ has: mobilePage.locator('papertitle') }).first();
      const title = await firstPaper.locator('papertitle').boundingBox();
      const media = await firstPaper.locator('.paper-media-cell').boundingBox();
      assert.ok(title.y + title.height <= media.y, 'Mobile paper titles precede their media');
      const selectedMarker = await mobilePage.locator('.paper-row-selected:visible .paper-media-cell').first().evaluate(el => {
        const style = getComputedStyle(el, '::before');
        return { content: style.content, display: style.display };
      });
      assert.match(selectedMarker.content, /selected/i);
      assert.notEqual(selectedMarker.display, 'none', 'Selected paper markers remain visible on mobile');
      const selectedBackground = await mobilePage.locator('.paper-row-selected:visible').first().evaluate(el => ({
        paper: getComputedStyle(el).backgroundColor,
        page: getComputedStyle(document.body).backgroundColor,
      }));
      assert.notEqual(selectedBackground.paper, 'rgba(0, 0, 0, 0)', 'Selected papers retain their background on mobile');
      assert.notEqual(selectedBackground.paper, selectedBackground.page);
      if (javaScriptEnabled) {
        await mobilePage.screenshot({ path: path.join(__dirname, '../.cache/homepage-mobile-hero.png') });
        await firstPaper.scrollIntoViewIfNeeded();
        await mobilePage.screenshot({ path: path.join(__dirname, '../.cache/homepage-mobile-research.png') });
        await mobilePage.locator('.site-nav-links a[href="#top"]').click();
      }
      const mobileMore = mobilePage.locator('#siteNavMore');
      await mobileMore.locator('summary').tap();
      await mobileMore.locator('a[href="#section-collab"]').tap();
      assert.equal(new URL(mobilePage.url()).hash, '#section-collab');
      if (javaScriptEnabled) assert.equal(await mobileMore.getAttribute('open'), null);
      await mobile.close();
      check(`touch navigation ${javaScriptEnabled ? 'with' : 'without'} JavaScript`);
    }

    for (const [scale, width, expected] of [[2, 1280, 480], [3, 375, 480]]) {
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

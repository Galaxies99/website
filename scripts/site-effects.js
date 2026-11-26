(function() {
  'use strict';

  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  var compactViewport = window.matchMedia('(max-width: 767px)');
  var stage = document.querySelector('.profile-stage');
  var nav = document.querySelector('.site-nav');
  var animations = new Set();

  // Animate only after intersection. Content stays readable before JS runs.
  function reveal(element, delay) {
    if (reducedMotion.matches || !element.animate) return;
    var animation = element.animate([
      { opacity: 0, transform: compactViewport.matches ? 'translateY(10px)' : 'translateY(18px)' },
      { opacity: 1, transform: 'translateY(0)' }
    ], {
      duration: compactViewport.matches ? 420 : 650,
      delay: compactViewport.matches ? Math.min(delay || 0, 120) : delay || 0,
      easing: 'cubic-bezier(0.2, 0.7, 0.3, 1)',
      fill: 'backwards'
    });
    animations.add(animation);
    animation.onfinish = function() { animations.delete(animation); };
  }

  if ('IntersectionObserver' in window) {
    var reveals = new IntersectionObserver(function(entries, observer) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        reveal(entry.target, Number(entry.target.dataset.revealDelay));
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.06 });

    document.querySelectorAll('.profile-name-row, .profile-intro, .profile-portrait, #profileCaption, .profile-link').forEach(function(element, index) {
      element.dataset.revealDelay = Math.min(index * 55, 330);
      reveals.observe(element);
    });
    document.querySelectorAll('.site-section .section-title, .news-list > li, .publications-table tr:not(.publications-head-row), .talks-list > li, .services-grid, .mentoring-group, .misc-subsection').forEach(function(element) {
      reveals.observe(element);
    });

    if (stage) {
      new IntersectionObserver(function(entries) {
        stage.classList.toggle('hero-in-view', entries[0].isIntersecting);
      }).observe(stage);
    }
  }

  // One scheduled update per frame for pointer and scroll feedback.
  var pointerFrame = 0;
  function resetPointer() {
    cancelAnimationFrame(pointerFrame);
    pointerFrame = 0;
    if (!stage) return;
    ['--pointer-x', '--pointer-y', '--portrait-x', '--portrait-y'].forEach(function(property) {
      stage.style.removeProperty(property);
    });
  }

  if (stage) {
    stage.addEventListener('pointermove', function(event) {
      if (reducedMotion.matches || compactViewport.matches || !finePointer.matches || event.pointerType === 'touch') return;
      cancelAnimationFrame(pointerFrame);
      pointerFrame = requestAnimationFrame(function() {
        var bounds = stage.getBoundingClientRect();
        var x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
        var y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
        stage.style.setProperty('--pointer-x', (x * 100).toFixed(1) + '%');
        stage.style.setProperty('--pointer-y', (y * 100).toFixed(1) + '%');
        stage.style.setProperty('--portrait-x', ((0.5 - y) * 7).toFixed(2) + 'deg');
        stage.style.setProperty('--portrait-y', ((x - 0.5) * 9).toFixed(2) + 'deg');
        pointerFrame = 0;
      });
    }, { passive: true });
    stage.addEventListener('pointerleave', resetPointer);
    window.addEventListener('blur', resetPointer);
  }

  reducedMotion.addEventListener('change', function() {
    resetPointer();
    if (reducedMotion.matches) {
      animations.forEach(function(animation) { animation.cancel(); });
      animations.clear();
    }
  });
  finePointer.addEventListener('change', resetPointer);
  compactViewport.addEventListener('change', resetPointer);

  document.addEventListener('visibilitychange', function() {
    document.documentElement.classList.toggle('effects-paused', document.hidden);
    if (document.hidden) resetPointer();
  });

  if (!nav) return;
  var links = Array.from(nav.querySelectorAll('a[href^="#"]'));
  var sections = links.map(function(link) {
    return document.querySelector(link.getAttribute('href'));
  });
  var more = nav.querySelector('.site-nav-more');
  var scrollFrame = 0;
  function updateScroll() {
    scrollFrame = 0;
    var height = document.documentElement.scrollHeight - window.innerHeight;
    var progress = height > 0 ? Math.max(0, Math.min(1, window.scrollY / height)) : 0;
    nav.style.setProperty('--reading-progress', progress.toFixed(4));
    var current = 0;
    var currentTop = -Infinity;
    var navBottom = nav.getBoundingClientRect().bottom + 100;
    sections.forEach(function(section, index) {
      if (!section) return;
      var top = section.getBoundingClientRect().top;
      if (top <= navBottom && top > currentTop) {
        current = index;
        currentTop = top;
      }
    });
    if (progress >= 0.999) current = links.length - 1;
    links.forEach(function(link, index) {
      if (index === current) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    if (more) more.classList.toggle('is-current', more.contains(links[current]));
  }
  function scheduleScroll() {
    if (!scrollFrame) scrollFrame = requestAnimationFrame(updateScroll);
  }
  window.addEventListener('scroll', scheduleScroll, { passive: true });
  window.addEventListener('resize', scheduleScroll);
  if ('ResizeObserver' in window) new ResizeObserver(scheduleScroll).observe(document.body);
  if (document.fonts) document.fonts.ready.then(scheduleScroll);
  updateScroll();
})();

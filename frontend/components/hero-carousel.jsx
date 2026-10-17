'use client';

import { useEffect, useRef, useState } from 'react';
import { Icon } from './ui';

const SLIDES = [
  {
    image: 'https://images.unsplash.com/photo-1518770660439-4636190af475?w=1920&q=80',
    label: 'Plan-first defense',
    title: 'Separate data\nfrom authority.',
    subtitle: 'Help AI agents complete your real task while treating emails, files, and tool outputs as information — not commands.',
    accent: '#1687ec',
  },
  {
    image: 'https://images.unsplash.com/photo-1550751827-4bd374c3972a?w=1920&q=80',
    label: 'Injection resistance',
    title: 'Block hidden\ninstructions.',
    subtitle: 'Attackers embed commands inside the data your agent reads. Agentguard scans, detects, and neutralizes them before they reach your tools.',
    accent: '#e2654f',
  },
  {
    image: 'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1920&q=80',
    label: 'Auditable execution',
    title: 'Every action\nleaves a trail.',
    subtitle: 'Inspect the plan, the security decisions, the injection detections, and the final answer — all in a live event timeline.',
    accent: '#44a47b',
  },
];

export function HeroCarousel() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    if (paused) return;
    timer.current = setInterval(() => {
      setIndex(prev => (prev + 1) % SLIDES.length);
    }, 6000);
    return () => clearInterval(timer.current);
  }, [paused]);

  function go(dir) {
    setIndex(prev => (prev + dir + SLIDES.length) % SLIDES.length);
  }

  return (
    <div
      className="hero-carousel"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="hero-slides" style={{ transform: `translateX(-${index * 100}%)` }}>
        {SLIDES.map((slide, i) => (
          <div className="hero-slide" key={i} style={{ opacity: i === index ? 1 : 0.4 }}>
            <div className="hero-slide-bg" style={{ backgroundImage: `url(${slide.image})` }} />
            <div className="hero-slide-overlay" />
            <div className="hero-slide-content">
              <span className="hero-slide-label" style={{ color: slide.accent }}>
                <Icon name="shield" /> {slide.label.toUpperCase()}
              </span>
              <h2 className="hero-slide-title">{slide.title}</h2>
              <p className="hero-slide-subtitle">{slide.subtitle}</p>
            </div>
          </div>
        ))}
      </div>

      <button className="hero-nav hero-nav-prev" onClick={() => go(-1)} aria-label="Previous slide">
        <Icon name="chevron" />
      </button>
      <button className="hero-nav hero-nav-next" onClick={() => go(1)} aria-label="Next slide">
        <Icon name="chevron" />
      </button>

      <div className="hero-dots">
        {SLIDES.map((_, i) => (
          <button
            key={i}
            className={`hero-dot ${i === index ? 'active' : ''}`}
            onClick={() => setIndex(i)}
            aria-label={`Go to slide ${i + 1}`}
          />
        ))}
      </div>

      <div className="hero-progress">
        {SLIDES.map((_, i) => (
          <div key={i} className={`hero-progress-bar ${i === index ? 'active' : ''} ${i < index ? 'done' : ''}`} />
        ))}
      </div>
    </div>
  );
}

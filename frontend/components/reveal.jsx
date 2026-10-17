'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Reveal — wraps children with a scroll-triggered animation.
 * Uses IntersectionObserver; falls back to visible on older browsers.
 *
 * Props:
 *  as: element tag (default 'div')
 *  delay: ms to delay the animation (default 0)
 *  direction: 'up' | 'down' | 'left' | 'right' | 'fade' | 'scale' (default 'up')
 *  threshold: 0–1, how much of the element must be visible (default 0.15)
 *  once: if true, animates only the first time (default true)
 *  className: additional classes
 */
export function Reveal({
  as: Tag = 'div',
  delay = 0,
  direction = 'up',
  threshold = 0.15,
  once = true,
  className = '',
  children,
  ...rest
}) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          if (once) observer.unobserve(el);
        } else if (!once) {
          setVisible(false);
        }
      },
      { threshold, rootMargin: '0px 0px -60px 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold, once]);

  return (
    <Tag
      ref={ref}
      className={`reveal reveal-${direction} ${visible ? 'reveal-in' : ''} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

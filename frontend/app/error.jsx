'use client';
export default function Error({ reset }) { return <div className="error-banner">This page could not load. <button className="button secondary" onClick={reset}>Try again</button></div>; }

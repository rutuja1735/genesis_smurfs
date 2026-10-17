import Link from 'next/link';

export function PublicBrand() {
  return <Link href="/" className="public-brand"><span className="brand-mark" aria-hidden="true" />Agentguard</Link>;
}

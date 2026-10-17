import { PublicBrand } from '../../components/public-brand';
import LoginForm from '../../components/login-form';
import { safeNext } from '../../lib/auth-session.mjs';

export const metadata = { title: 'Sign in' };
export default async function Page({ searchParams }) {
  const query = await searchParams;
  return <div className="auth-page"><header><PublicBrand /></header><LoginForm next={safeNext(query.next)} /><footer>Plan first. Execute safely. Keep a clear record.</footer></div>;
}

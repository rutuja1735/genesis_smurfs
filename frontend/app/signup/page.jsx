import { PublicBrand } from '../../components/public-brand';
import LoginForm from '../../components/login-form';
export const metadata = { title: 'Get started' };
export default function Page() {
  return <div className="auth-page"><header><PublicBrand /></header><LoginForm signup next="/dashboard" /><footer>Plan first. Execute safely. Keep a clear record.</footer></div>;
}

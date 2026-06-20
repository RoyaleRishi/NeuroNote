import Link from "next/link";
import { OAuthButtons } from "../../components/auth/OAuthButtons";

export default function LoginPage() {
  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card-header">
          <h1 className="login-card-brand">NeuroNote</h1>
          <p className="login-card-sub">Sign in to your workspace</p>
        </div>
        <OAuthButtons />
        <p className="login-card-footer-link">
          <Link href="/landing">What is NeuroNote? →</Link>
        </p>
      </div>
    </div>
  );
}

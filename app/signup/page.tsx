import { AuthForm } from "../components/auth-form";

export default function SignupPage() {
  return (
    <main className="page page--auth">
      <AuthForm mode="sign-up" />
    </main>
  );
}

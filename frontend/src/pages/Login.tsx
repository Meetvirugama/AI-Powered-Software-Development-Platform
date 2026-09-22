export function Login() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <div className="p-8 space-y-4 border rounded-xl shadow-lg bg-card w-96">
        <h1 className="text-2xl font-bold text-center text-foreground">Login</h1>
        <p className="text-center text-muted-foreground">
          Authenticate with GitHub to access the platform.
        </p>
        <button className="w-full py-2 font-semibold bg-primary text-primary-foreground rounded-lg">
          Login with GitHub
        </button>
      </div>
    </div>
  );
}

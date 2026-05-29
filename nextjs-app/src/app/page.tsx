import { redirect } from "next/navigation";
import { getSessionUser } from "@/lib/auth/session";
import OpenCodeFrame from "@/components/OpenCodeFrame";

export default async function Home() {
  const user = await getSessionUser();
  if (!user) {
    redirect("/api/auth/login");
  }

  return (
    <div className="dashboard">
      <header className="topbar">
        <span className="topbar-brand">Agent Auth POC</span>
        <div className="topbar-user">
          <span className="name">
            {user.given_name} {user.family_name}
          </span>
          <span className="roles">{user.roles.filter(r => !r.startsWith("default-")).join(", ")}</span>
          <a href="/api/auth/logout">
            <button className="logout-btn">Logout</button>
          </a>
        </div>
      </header>
      <div className="iframe-wrapper">
        <OpenCodeFrame />
      </div>
    </div>
  );
}

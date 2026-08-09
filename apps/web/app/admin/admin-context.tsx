"use client";

import { createContext, useContext } from "react";

import type { Theme } from "@/lib/server-api";

export interface Me {
  user_id: string;
  tenant_slug: string;
  email: string;
  permissions: string[];
}

export interface AdminContextValue {
  me: Me;
  theme: Theme | null;
}

export const AdminContext = createContext<AdminContextValue | null>(null);

export function useAdmin(): AdminContextValue {
  const value = useContext(AdminContext);
  if (value === null) {
    throw new Error("useAdmin() called outside app/admin's layout");
  }
  return value;
}

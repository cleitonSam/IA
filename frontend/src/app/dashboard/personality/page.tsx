"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";

// This page has been merged into /dashboard/settings (tab: Personalidade IA)
export default function PersonalityPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/settings");
  }, [router]);
  return null;
}

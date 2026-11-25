/** Cấu hình dùng chung cho tầng services. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

/** Giai đoạn mock-first: true cho tới khi nối FastAPI (đặt NEXT_PUBLIC_USE_MOCK=false). */
export const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK !== "false";

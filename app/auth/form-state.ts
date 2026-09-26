export type AuthFormState = {
  status: "idle" | "error" | "success";
  message: string;
};

export const initialAuthFormState: AuthFormState = {
  status: "idle",
  message: "",
};

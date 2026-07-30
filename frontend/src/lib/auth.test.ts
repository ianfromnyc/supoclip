import { isSignUpDisabled } from "./auth";

describe("isSignUpDisabled", () => {
  it("disables sign-ups when DISABLE_SIGN_UP is unset", () => {
    expect(isSignUpDisabled(undefined)).toBe(true);
  });

  it.each(["false", "0", "no", "FALSE", "No", " false "])(
    "opens sign-ups for the explicit opt-out value %j",
    (value) => {
      expect(isSignUpDisabled(value)).toBe(false);
    }
  );

  it.each(["true", "1", "yes", "TRUE", "", "   ", "garbage"])(
    "keeps sign-ups closed for %j",
    (value) => {
      expect(isSignUpDisabled(value)).toBe(true);
    }
  );
});

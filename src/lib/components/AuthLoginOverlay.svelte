<script lang="ts">
  import { ArrowRight, CheckCircle2, ChevronDown, ShieldCheck, Sparkles } from "lucide-svelte";

  import type { LoginHcaptchaConfig } from "$lib/types";

  type LocaleOption = {
    value: string;
    label: string;
  };

  type UiCopy = {
    privateGateway: string;
    appTitle: string;
    loginLede: string;
    forgeTagline: string;
    forgeStory: string;
    forgeDescription: string;
    forgeTaskDriven: string;
    forgeValidationFirst: string;
    forgeControlledExecution: string;
    enterWorkspace: string;
    localGatewayNotice: string;
    language: string;
    password: string;
    signingIn: string;
    signIn: string;
  };

  let {
    ui,
    localeOptions,
    activeLocale,
    loginPassword = $bindable(""),
    loginBusy,
    loginMessage,
    loginHcaptcha,
    loginHcaptchaToken,
    loginHcaptchaContainer = $bindable(null),
    onLocaleChange,
    onSubmit
  }: {
    ui: UiCopy;
    localeOptions: readonly LocaleOption[];
    activeLocale: string;
    loginPassword: string;
    loginBusy: boolean;
    loginMessage: string;
    loginHcaptcha: LoginHcaptchaConfig;
    loginHcaptchaToken: string;
    loginHcaptchaContainer: HTMLDivElement | null;
    onLocaleChange: (locale: string) => void;
    onSubmit: () => void | Promise<void>;
  } = $props();
</script>

<div class="forge-auth-backdrop absolute inset-0"></div>
<div class="absolute inset-0 z-10 flex items-center justify-center p-4 sm:p-8">
  <div class="auth-dialog-card grid w-full max-w-5xl overflow-hidden rounded-[2rem] border border-white/10 bg-[#11131a] shadow-[0_40px_120px_rgba(5,8,18,0.52)] lg:grid-cols-[1.08fr_0.92fr]">
    <section class="forge-auth-story relative hidden min-h-[35rem] overflow-hidden p-10 text-white lg:flex lg:flex-col lg:justify-between">
      <div class="relative z-10">
        <div class="inline-flex items-center gap-3">
          <div class="forge-mark forge-mark--large">F</div>
          <div>
            <p class="text-xl font-semibold tracking-tight">ForgeOS</p>
            <p class="text-[10px] font-bold uppercase tracking-[0.24em] text-white/45">Enterprise AI Native Platform</p>
          </div>
        </div>
        <div class="mt-20 max-w-md">
          <p class="text-xs font-bold uppercase tracking-[0.26em] text-[#8b7cff]">{ui.forgeTagline}</p>
          <h1 class="mt-4 text-4xl font-semibold leading-tight tracking-[-0.04em]">{ui.forgeStory}</h1>
          <p class="mt-5 max-w-md text-sm leading-7 text-white/55">{ui.forgeDescription}</p>
        </div>
      </div>
      <div class="relative z-10 grid grid-cols-3 gap-3">
        <div class="forge-auth-metric"><Sparkles size={15} /><span>{ui.forgeTaskDriven}</span></div>
        <div class="forge-auth-metric"><CheckCircle2 size={15} /><span>{ui.forgeValidationFirst}</span></div>
        <div class="forge-auth-metric"><ShieldCheck size={15} /><span>{ui.forgeControlledExecution}</span></div>
      </div>
    </section>

    <section class="flex min-h-[35rem] flex-col justify-center bg-white p-6 sm:p-10 lg:p-12">
      <div class="mb-9 flex items-start justify-between gap-4">
        <div>
          <div class="mb-5 flex items-center gap-3 lg:hidden">
            <div class="forge-mark">F</div>
            <span class="text-lg font-semibold text-gray-950">ForgeOS</span>
          </div>
          <p class="text-[10px] font-bold uppercase tracking-[0.24em] text-violet-600">{ui.privateGateway}</p>
          <h2 class="mt-3 text-3xl font-semibold tracking-tight text-gray-950">{ui.enterWorkspace}</h2>
          <p class="mt-3 max-w-sm text-sm leading-6 text-gray-500">{ui.loginLede}</p>
        </div>
        <label class="flex min-w-[8.5rem] flex-col gap-1.5">
          <span class="sr-only">{ui.language}</span>
          <div class="relative">
            <select
              aria-label={ui.language}
              class="auth-dialog-select w-full appearance-none rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 pr-8 text-xs font-semibold text-gray-600 outline-none transition focus:border-violet-400 focus:ring-4 focus:ring-violet-100"
              onchange={(event) => onLocaleChange((event.currentTarget as HTMLSelectElement).value)}
              value={activeLocale}
            >
              {#each localeOptions as option (option.value)}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
            <div class="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-gray-400">
              <ChevronDown size={14} />
            </div>
          </div>
        </label>
      </div>

      <form
      class="space-y-5"
      data-testid="login-form"
      onsubmit={(event) => {
        event.preventDefault();
        void onSubmit();
      }}
    >
      <label class="block space-y-2">
        <span class="text-sm font-semibold text-gray-700">{ui.password}</span>
        <input
          bind:value={loginPassword}
          autocomplete="current-password"
          class="auth-dialog-input w-full rounded-xl border border-gray-200 bg-gray-50 px-4 py-3.5 text-sm text-gray-900 outline-none transition focus:border-violet-500 focus:bg-white focus:ring-4 focus:ring-violet-100"
          data-testid="login-password"
          placeholder={ui.password}
          type="password"
        />
      </label>

      {#if loginHcaptcha.enabled && loginHcaptcha.siteKey}
        <div
          bind:this={loginHcaptchaContainer}
          class="auth-dialog-hcaptcha min-h-[82px] overflow-hidden rounded-2xl border border-gray-200 bg-white px-3 py-3 shadow-sm"
        ></div>
      {/if}

      <button
        class="forge-auth-submit inline-flex w-full items-center justify-center gap-2 rounded-xl px-5 py-3.5 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-45"
        data-testid="login-submit"
        disabled={loginBusy || (loginHcaptcha.enabled && !loginHcaptchaToken)}
        type="submit"
      >
        {loginBusy ? ui.signingIn : ui.signIn}
        {#if !loginBusy}<ArrowRight size={16} />{/if}
      </button>
    </form>

    {#if loginMessage}
      <p class="auth-dialog-message mt-4 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{loginMessage}</p>
    {/if}
      <div class="mt-8 flex items-center gap-2 border-t border-gray-100 pt-5 text-[11px] font-medium text-gray-400">
        <ShieldCheck size={13} />
        <span>{ui.localGatewayNotice}</span>
      </div>
    </section>
  </div>
</div>

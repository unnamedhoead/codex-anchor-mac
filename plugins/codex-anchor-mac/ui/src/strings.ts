export type Lang = 'en' | 'zh';
export interface Strings { [key: string]: string | ((arg: string) => string); }

export const STR: Record<Lang, Strings> = {
  en: {
    sub: 'One tiny scheduled request a day, so your 5-hour quota window starts when you need it',
    nextRun: 'Next run', changeTime: 'Change time', controls: 'Controls', recentRuns: 'Recent runs',
    jobState: 'Job', pmsetWake: 'pmset wake', shouldBe: 'should be',
    timezone: 'Timezone', systemClock: 'System clock',
    save: 'Save', runNow: 'Run now', enable: 'Enable', disable: 'Disable',
    timeHint: 'The time is read in the timezone you pick, then converted to the system clock that launchd understands. The pmset wake is set 3 minutes earlier automatically.',
    runNowHint: 'Running now opens a 5-hour window immediately',
    sameZone: 'same as chosen timezone', noRuns: '(no runs yet)', loading: 'Loading…',
    notConfigured: 'not configured', notLoaded: 'not loaded', notSet: 'not set',
    loaded: 'loaded, waiting', running: 'running', lastExit: 'last exit',
    never: 'never run yet',
    confirmRun: 'Send a real request now? This opens a 5-hour window immediately.',
    warnDrift: tz => `System timezone changed to ${tz}. The schedule was computed for a different one — press Save to re-sync.`,
    warnWake: 'pmset wake does not match the trigger time; the job may be late on battery nights',
    langButton: '中文',
  },
  zh: {
    sub: '每天定时发一次极小的请求，把 5 小时额度窗口锚定在你需要的位置',
    nextRun: '下次触发', changeTime: '修改时间', controls: '控制', recentRuns: '最近运行',
    jobState: '任务状态', pmsetWake: 'pmset 唤醒', shouldBe: '应为',
    timezone: '时区', systemClock: '系统时钟',
    save: '保存', runNow: '立即跑一次', enable: '启用', disable: '停用',
    timeHint: '时间按所选时区解释，再换算成 launchd 认得的系统本地时间。pmset 唤醒自动设为提前 3 分钟。',
    runNowHint: '立即跑会当场开一个 5 小时窗口',
    sameZone: '与所选时区相同', noRuns: '（暂无记录）', loading: '加载中…',
    notConfigured: '未配置', notLoaded: '未加载', notSet: '未设置',
    loaded: '已加载，待触发', running: '运行中', lastExit: '上次退出码',
    never: '尚未运行过',
    confirmRun: '立即发一次真实请求？这会当场开启一个 5 小时窗口。',
    warnDrift: tz => `系统时区已变为 ${tz}，当前计划是按另一个时区算的 —— 点「保存」重新同步。`,
    warnWake: 'pmset 唤醒时间与触发时间不匹配，没插电的夜里可能迟到',
    langButton: 'EN',
  },
};

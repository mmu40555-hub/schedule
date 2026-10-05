from datetime import date, timedelta


# 首次运行的演示数据与内部计数工具。
class SeedMixin:
    # ================= 首次运行的演示数据 =================

    def _seed_if_empty(self) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM daily_tasks").fetchone()
        if row["n"]:
            return

        today = date.today()
        yesterday = today - timedelta(days=1)

        daily_specs = [
            ("俯卧撑", "每日健身", False, "", ""),
            ("跑步 5 km", "每日健身", False, "", ""),
            ("背单词", "学习", False, "", ""),
            ("阅读 30 分钟", "学习", False, "", ""),
            ("给绿植浇水", "生活", False, "", ""),
            ("整理本周会议纪要", "", False, "", ""),
            ("完成今日工作周报", "", True, "15:00", "按时提交到周报系统"),
        ]
        daily_ids: dict[str, int] = {}
        for title, group, has_deadline, time_text, note in daily_specs:
            # 创建日设为前天，这样能演示「最新连续」与「最高连续」的差别
            daily_ids[title] = self.create_daily_task(
                title, group, has_deadline, time_text, note,
                created_day=(today - timedelta(days=2)).isoformat(),
            )

        # 前天：背单词完成，其余漏勾
        self._insert_record(daily_ids["背单词"], today - timedelta(days=2), done=True)
        # 昨天：俯卧撑、背单词、跑步完成 → 背单词连续 2 天
        self._insert_record(daily_ids["俯卧撑"], yesterday, done=True)
        self._insert_record(daily_ids["背单词"], yesterday, done=True)
        self._insert_record(daily_ids["跑步 5 km"], yesterday, done=True)
        # 阅读、整理会议纪要、给绿植浇水 昨天未勾，会出现在陈年旧账里

        self.create_once_task(
            "抢演唱会门票", today.isoformat(), "08:00", "提前登录账号", group_name="娱乐"
        )
        self.create_once_task(
            "给客户回电话确认排期", today.isoformat(), "17:30", "", group_name="工作"
        )
        self.create_once_task(
            "回复张老师关于课题的邮件", yesterday.isoformat(), "", "", group_name="工作"
        )
        # 远期任务两种显示时机各来一个：前者每天都挂在首页，后者等到倒数三天才出现
        self.create_once_task(
            "预约下周体检", (today + timedelta(days=10)).isoformat(), "", "每天都提醒，别忘了",
            always_show=True, group_name="生活",
        )
        self.create_once_task(
            "续费域名", (today + timedelta(days=12)).isoformat(), "", "到期前三天才会冒出来",
            group_name="工作",
        )

        self.create_period_task(
            "完成毕业论文",
            (today + timedelta(days=45)).isoformat(),
            "分三个阶段推进，每个阶段完成后再进入下一阶段",
            [
                ("综述章节", (today + timedelta(days=12)).isoformat()),
                ("正文初稿", (today + timedelta(days=30)).isoformat()),
                ("终稿定稿并上传", (today + timedelta(days=45)).isoformat()),
            ],
            group_name="学业",
        )
        report_id = self.create_period_task(
            "提交项目结题报告",
            today.isoformat(),
            "最终期限就是今天",
            [
                ("整理实验数据", (today - timedelta(days=10)).isoformat()),
                ("撰写报告正文", today.isoformat()),
            ],
            group_name="工作",
        )
        first_stage = self.list_stages(report_id)[0]
        self.conn.execute(
            "UPDATE period_stages SET done=1 WHERE id=?", (first_stage.id,)
        )
        self.conn.commit()

    def _insert_record(self, task_id: int, day: date, done: bool) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO daily_records (daily_task_id, day, done) VALUES (?,?,?)",
            (task_id, day.isoformat(), int(done)),
        )
        self.conn.commit()

    def _next_order(self, table: str) -> int:
        row = self.conn.execute(f"SELECT COALESCE(MAX(sort_order), 0) + 1 FROM {table}").fetchone()
        return int(row[0])

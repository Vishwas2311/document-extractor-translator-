import type { DocumentDetail, PageResult, TextBlock } from "./types";

function block(
  id: string,
  order: number,
  source: string,
  translation: string,
  language: string,
  polygon: Array<{ x: number; y: number }>,
  role: string | null = null,
  confidence = 0.97,
): TextBlock {
  return {
    block_id: id,
    reading_order: order,
    role,
    source_text: source,
    translated_text: translation,
    source_language: language,
    ocr_confidence: confidence,
    translation_status: "translated",
    bounding_regions: [{ page_number: 1, polygon }],
    review_required: confidence < 0.9,
    warnings: confidence < 0.9 ? ["Low OCR confidence — review recommended."] : [],
  };
}

function page(
  pageNumber: number,
  sourceText: string,
  translatedText: string,
  blocks: TextBlock[],
): PageResult {
  return {
    schema_version: "1.0",
    document_id: "demo-youth-care-intake",
    document_status: "needs_review",
    page: {
      page_number: pageNumber,
      page_count: 3,
      width: 8.5,
      height: 11,
      unit: "inch",
      angle: 0,
      source_text: sourceText,
      translated_text: translatedText,
    },
    blocks: blocks.map((item) => ({
      ...item,
      bounding_regions: item.bounding_regions.map((region) => ({
        ...region,
        page_number: pageNumber,
      })),
    })),
    tables: [],
    warnings: pageNumber === 3 ? ["One handwriting region requires human review."] : [],
  };
}

const pageOneBlocks = [
  block("p1-title", 1, "استمارة دعم الشباب", "Youth Support Intake Form", "ar", [
    { x: 1.25, y: 1.08 }, { x: 7.3, y: 1.08 }, { x: 7.3, y: 1.58 }, { x: 1.25, y: 1.58 },
  ], "title", 0.99),
  block("p1-intro", 2, "يرجى تعبئة هذه الاستمارة لمساعدتنا على فهم احتياجات الشاب وتقديم الدعم المناسب.", "Please complete this form so we can understand the young person's needs and provide appropriate support.", "ar", [
    { x: 0.9, y: 2.0 }, { x: 7.62, y: 2.0 }, { x: 7.62, y: 2.62 }, { x: 0.9, y: 2.62 },
  ]),
  block("p1-name", 3, "الاسم الكامل: أحمد محمود", "Full name: Ahmed Mahmoud", "ar", [
    { x: 0.9, y: 3.12 }, { x: 4.45, y: 3.12 }, { x: 4.45, y: 3.5 }, { x: 0.9, y: 3.5 },
  ]),
  block("p1-dob", 4, "تاريخ الميلاد: ١٤ / ٠٣ / ٢٠١٠", "Date of birth: 14 / 03 / 2010", "ar", [
    { x: 4.75, y: 3.12 }, { x: 7.62, y: 3.12 }, { x: 7.62, y: 3.5 }, { x: 4.75, y: 3.5 },
  ]),
  block("p1-concern", 5, "سبب الإحالة: يحتاج إلى دعم في المدرسة والتواصل مع الأسرة.", "Reason for referral: Needs support at school and with family communication.", "ar", [
    { x: 0.9, y: 4.18 }, { x: 7.62, y: 4.18 }, { x: 7.62, y: 4.88 }, { x: 0.9, y: 4.88 },
  ], null, 0.94),
  block("p1-consent", 6, "أوافق على استخدام هذه المعلومات لتنسيق خدمات الرعاية.", "I consent to this information being used to coordinate care services.", "ar", [
    { x: 0.9, y: 7.35 }, { x: 7.62, y: 7.35 }, { x: 7.62, y: 8.02 }, { x: 0.9, y: 8.02 },
  ]),
];

const pageTwoBlocks = [
  block("p2-title", 1, "青少年情况评估", "Youth Situation Assessment", "zh-Hans", [
    { x: 1.55, y: 1.05 }, { x: 6.92, y: 1.05 }, { x: 6.92, y: 1.58 }, { x: 1.55, y: 1.58 },
  ], "title", 0.99),
  block("p2-home", 2, "家庭情况：与母亲、父亲和妹妹共同居住。家庭最近搬到了新的城市。", "Family situation: Lives with mother, father, and younger sister. The family recently moved to a new city.", "zh-Hans", [
    { x: 0.9, y: 2.15 }, { x: 7.62, y: 2.15 }, { x: 7.62, y: 2.94 }, { x: 0.9, y: 2.94 },
  ]),
  block("p2-school", 3, "学校情况：出勤率有所下降，在数学课上感到困难。", "School situation: Attendance has declined and the young person is finding mathematics difficult.", "zh-Hans", [
    { x: 0.9, y: 3.55 }, { x: 7.62, y: 3.55 }, { x: 7.62, y: 4.24 }, { x: 0.9, y: 4.24 },
  ]),
  block("p2-strength", 4, "优势和兴趣：喜欢绘画、足球和电脑。与妹妹关系亲密。", "Strengths and interests: Enjoys drawing, football, and computers. Has a close relationship with their sister.", "zh-Hans", [
    { x: 0.9, y: 4.84 }, { x: 7.62, y: 4.84 }, { x: 7.62, y: 5.57 }, { x: 0.9, y: 5.57 },
  ]),
  block("p2-plan", 5, "建议：安排学校支持会议，并为家长提供翻译协助。", "Recommendation: Arrange a school support meeting and provide interpreting assistance for the parents.", "zh-Hans", [
    { x: 0.9, y: 6.26 }, { x: 7.62, y: 6.26 }, { x: 7.62, y: 6.98 }, { x: 0.9, y: 6.98 },
  ], null, 0.92),
];

const pageThreeBlocks = [
  block("p3-title", 1, "متابعة / 后续记录", "Follow-up Notes", "mixed", [
    { x: 1.72, y: 1.06 }, { x: 6.78, y: 1.06 }, { x: 6.78, y: 1.58 }, { x: 1.72, y: 1.58 },
  ], "title", 0.98),
  block("p3-note1", 2, "تم الاجتماع مع الأسرة بحضور مترجم.", "The family meeting took place with an interpreter present.", "ar", [
    { x: 0.9, y: 2.2 }, { x: 7.62, y: 2.2 }, { x: 7.62, y: 2.78 }, { x: 0.9, y: 2.78 },
  ]),
  block("p3-note2", 3, "家长同意学校联系支持团队。", "The parents agreed that the school may contact the support team.", "zh-Hans", [
    { x: 0.9, y: 3.22 }, { x: 7.62, y: 3.22 }, { x: 7.62, y: 3.79 }, { x: 0.9, y: 3.79 },
  ]),
  block("p3-action", 4, "موعد المتابعة الأسبوع القادم — 联系人：李老师", "Follow-up is scheduled for next week — Contact: Teacher Li.", "mixed", [
    { x: 0.9, y: 4.34 }, { x: 7.62, y: 4.34 }, { x: 7.62, y: 5.02 }, { x: 0.9, y: 5.02 },
  ], null, 0.86),
];

export const demoPages: PageResult[] = [
  page(1, pageOneBlocks.map((item) => item.source_text).join("\n"), pageOneBlocks.map((item) => item.translated_text).join("\n"), pageOneBlocks),
  page(2, pageTwoBlocks.map((item) => item.source_text).join("\n"), pageTwoBlocks.map((item) => item.translated_text).join("\n"), pageTwoBlocks),
  page(3, pageThreeBlocks.map((item) => item.source_text).join("\n"), pageThreeBlocks.map((item) => item.translated_text).join("\n"), pageThreeBlocks),
];

demoPages[0].tables = [
  {
    table_id: "t0001",
    row_count: 3,
    column_count: 2,
    bounding_regions: [
      { page_number: 1, polygon: [{ x: 0.9, y: 5.25 }, { x: 7.62, y: 5.25 }, { x: 7.62, y: 6.95 }, { x: 0.9, y: 6.95 }] },
    ],
    cells: [
      { cell_id: "t0001-c0001", row_index: 0, column_index: 0, row_span: 1, column_span: 1, kind: "columnHeader", content: "مجال الدعم", source_language: "ar", translated_content: "Support area", translation_status: "translated", bounding_regions: [] },
      { cell_id: "t0001-c0002", row_index: 0, column_index: 1, row_span: 1, column_span: 1, kind: "columnHeader", content: "الأولوية", source_language: "ar", translated_content: "Priority", translation_status: "translated", bounding_regions: [] },
      { cell_id: "t0001-c0003", row_index: 1, column_index: 0, row_span: 1, column_span: 1, content: "الدعم المدرسي", source_language: "ar", translated_content: "School support", translation_status: "translated", bounding_regions: [] },
      { cell_id: "t0001-c0004", row_index: 1, column_index: 1, row_span: 1, column_span: 1, content: "عالية", source_language: "ar", translated_content: "High", translation_status: "translated", bounding_regions: [] },
      { cell_id: "t0001-c0005", row_index: 2, column_index: 0, row_span: 1, column_span: 1, content: "التواصل الأسري", source_language: "ar", translated_content: "Family communication", translation_status: "translated", bounding_regions: [] },
      { cell_id: "t0001-c0006", row_index: 2, column_index: 1, row_span: 1, column_span: 1, content: "متوسطة", source_language: "ar", translated_content: "Medium", translation_status: "translated", bounding_regions: [] },
    ],
  },
];

export const demoDocument: DocumentDetail = {
  id: "demo-youth-care-intake",
  original_filename: "sample.pdf",
  content_type: "application/pdf",
  status: "needs_review",
  page_count: 3,
  current_stage: "Ready for review",
  progress_percent: 100,
  safe_error_message: null,
  created_at: "2026-07-31T09:30:00Z",
  updated_at: "2026-07-31T09:31:18Z",
  pages: demoPages,
  demo: true,
};

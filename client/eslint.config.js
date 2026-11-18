import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**', '**/*.d.ts'] },
  {
    files: ['**/*.{ts,vue}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      ...vue.configs['flat/recommended'],
    ],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.browser },
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      // 项目里存在少量刻意的 any（防御性解析外部数据），不强制 no-explicit-any
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      // 关闭纯排版/风格规则： codebase 已有既定格式，避免上千条噪音淹没真正的问题。
      // 这些交给人工/格式化工具，不进 lint 门禁。
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      'vue/attributes-order': 'off',
      'vue/html-closing-bracket-newline': 'off',
      'vue/html-indent': 'off',
      'vue/html-self-closing': 'off',
      'vue/first-attribute-linebreak': 'off',
      // 安全相关：v-html 仅警告（项目已用白名单 markdown 渲染，唯一命中已知）
      'vue/no-v-html': 'warn',
    },
  },
)

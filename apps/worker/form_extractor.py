from __future__ import annotations

import re
from typing import Any

from apps.api.app.schemas import WorkerFieldOption, WorkerFieldState


def extract_form_fields(page) -> list[WorkerFieldState]:
    raw_fields = page.evaluate(
        """
        () => {
          const compress = (value) => (value || '').replace(/\\s+/g, ' ').trim()
          const attr = (element, name) => compress(element.getAttribute(name))
          const text = (element) => compress(element?.innerText || element?.textContent || '')
          const isVisible = (element) => {
            const style = window.getComputedStyle(element)
            const rect = element.getBoundingClientRect()
            return (
              style.display !== 'none' &&
              style.visibility !== 'hidden' &&
              rect.width > 0 &&
              rect.height > 0
            )
          }
          const quote = (value) => String(value).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\\\"')
          const xpathForElement = (element) => {
            if (element.id) {
              return `//*[@id="${quote(element.id)}"]`
            }
            const parts = []
            let current = element
            while (current && current.nodeType === Node.ELEMENT_NODE) {
              const siblings = current.parentNode
                ? Array.from(current.parentNode.children).filter(
                    (candidate) => candidate.tagName === current.tagName
                  )
                : [current]
              const index = siblings.indexOf(current) + 1
              parts.unshift(`${current.tagName.toLowerCase()}[${index}]`)
              current = current.parentElement
            }
            return `//${parts.join('/')}`
          }
          const selectorFor = (element) => {
            const tag = element.tagName.toLowerCase()
            if (element.id) {
              return `#${CSS.escape(element.id)}`
            }
            const name = attr(element, 'name')
            if (name) {
              return `${tag}[name="${quote(name)}"]`
            }
            const ariaLabel = attr(element, 'aria-label')
            if (ariaLabel) {
              return `${tag}[aria-label="${quote(ariaLabel)}"]`
            }
            const placeholder = attr(element, 'placeholder')
            if (placeholder) {
              return `${tag}[placeholder="${quote(placeholder)}"]`
            }
            return `xpath=${xpathForElement(element)}`
          }
          const labelText = (element) => {
            const associatedLabels = element.labels ? Array.from(element.labels) : []
            const directLabels = associatedLabels.map((label) => text(label)).filter(Boolean)
            if (directLabels.length) {
              return directLabels.join(' ')
            }
            const labelledBy = attr(element, 'aria-labelledby')
            if (labelledBy) {
              const ariaLabels = labelledBy
                .split(' ')
                .map((id) => text(document.getElementById(id)))
                .filter(Boolean)
              if (ariaLabels.length) {
                return ariaLabels.join(' ')
              }
            }
            const parentLabel = element.closest('label')
            if (parentLabel) {
              return text(parentLabel)
            }
            return ''
          }
          const questionText = (element, label) => {
            const wrapper = element.closest('fieldset, section, div, li, label')
            const legend = text(element.closest('fieldset')?.querySelector('legend'))
            const description = attr(element, 'aria-describedby')
              .split(' ')
              .map((id) => text(document.getElementById(id)))
              .filter(Boolean)
              .join(' ')
            return compress(
              [label, attr(element, 'aria-label'), attr(element, 'placeholder'), legend, description, text(wrapper)]
                .filter(Boolean)
                .join(' ')
            )
          }
          const sectionText = (element) => {
            const sectionRoot = element.closest('fieldset, section, article, div')
            if (!sectionRoot) {
              return ''
            }
            const heading = sectionRoot.querySelector('legend, h1, h2, h3, h4, h5, h6')
            return text(heading)
          }
          const makeBaseRecord = (element, extra = {}) => {
            const tag = element.tagName.toLowerCase()
            const inputType = tag === 'input' ? (attr(element, 'type') || 'text').toLowerCase() : tag
            const label = labelText(element)
            const question = questionText(element, label)
            const required =
              element.required ||
              attr(element, 'aria-required') === 'true' ||
              /required/i.test(question)
            return {
              field_type:
                inputType === 'radio'
                  ? 'radio'
                  : inputType === 'checkbox'
                    ? 'checkbox'
                    : inputType === 'file'
                      ? 'file'
                      : tag === 'textarea'
                        ? 'textarea'
                        : tag === 'select'
                          ? 'select'
                          : 'text',
              input_type: inputType,
              html_name: attr(element, 'name') || null,
              html_id: attr(element, 'id') || null,
              placeholder: attr(element, 'placeholder') || null,
              label,
              question_text: question,
              required,
              section: sectionText(element) || null,
              selector: selectorFor(element),
              ...extra,
            }
          }

          const groupedRecords = new Map()
          const output = []
          for (const element of Array.from(document.querySelectorAll('input, textarea, select'))) {
            const tag = element.tagName.toLowerCase()
            const inputType = tag === 'input' ? (attr(element, 'type') || 'text').toLowerCase() : tag
            if (inputType === 'hidden' || !isVisible(element)) {
              continue
            }

            if (inputType === 'radio') {
              const groupKey = `radio:${attr(element, 'name') || attr(element, 'id') || selectorFor(element)}`
              const group = groupedRecords.get(groupKey) || {
                ...makeBaseRecord(element),
                options: [],
              }
              group.options.push({
                label: labelText(element) || attr(element, 'value') || 'Option',
                value: attr(element, 'value') || labelText(element) || 'option',
                selector: selectorFor(element),
              })
              groupedRecords.set(groupKey, group)
              continue
            }

            if (inputType === 'checkbox' && attr(element, 'name')) {
              const groupKey = `checkbox:${attr(element, 'name')}`
              const count = document.querySelectorAll(
                `input[type="checkbox"][name="${CSS.escape(attr(element, 'name'))}"]`
              ).length
              if (count > 1) {
                const group = groupedRecords.get(groupKey) || {
                  ...makeBaseRecord(element),
                  options: [],
                }
                group.options.push({
                  label: labelText(element) || attr(element, 'value') || 'Option',
                  value: attr(element, 'value') || labelText(element) || 'option',
                  selector: selectorFor(element),
                })
                groupedRecords.set(groupKey, group)
                continue
              }
            }

            if (tag === 'select') {
              output.push({
                ...makeBaseRecord(element),
                options: Array.from(element.options).map((option) => ({
                  label: text(option) || attr(option, 'value') || 'Option',
                  value: attr(option, 'value') || text(option) || 'option',
                  selector: selectorFor(element),
                })),
              })
              continue
            }

            output.push({
              ...makeBaseRecord(element),
              options: [],
            })
          }

          return [...output, ...Array.from(groupedRecords.values())]
        }
        """
    )
    return [_to_field_state(item, index) for index, item in enumerate(raw_fields)]


def _to_field_state(item: dict[str, Any], index: int) -> WorkerFieldState:
    field_id = _build_field_id(item, index)
    options = [
        WorkerFieldOption(
            label=str(option.get("label") or "Option"),
            value=str(option.get("value") or ""),
            selector=str(option.get("selector") or item.get("selector") or ""),
        )
        for option in item.get("options", [])
    ]
    return WorkerFieldState(
        field_id=field_id,
        label=str(item.get("label") or ""),
        question_text=str(item.get("question_text") or ""),
        selector=str(item.get("selector") or ""),
        field_type=str(item.get("field_type") or "text"),
        input_type=item.get("input_type"),
        html_name=item.get("html_name"),
        html_id=item.get("html_id"),
        placeholder=item.get("placeholder"),
        required=bool(item.get("required")),
        options=options,
        section=item.get("section"),
    )


def _build_field_id(item: dict[str, Any], index: int) -> str:
    for candidate in [item.get("html_id"), item.get("html_name"), item.get("label")]:
        if candidate:
            return _slugify(str(candidate))
    return f"field-{index}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "field"

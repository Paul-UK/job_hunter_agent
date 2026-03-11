from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Error as PlaywrightError

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
          const selectorCandidatesFor = (element) => {
            const tag = element.tagName.toLowerCase()
            const candidates = []
            const push = (candidate) => {
              if (candidate && !candidates.includes(candidate)) {
                candidates.push(candidate)
              }
            }
            if (element.id) {
              push(`#${CSS.escape(element.id)}`)
            }
            if (tag === 'label') {
              const htmlFor = attr(element, 'for')
              if (htmlFor) {
                push(`label[for="${quote(htmlFor)}"]`)
              }
            }
            const dataTestId = attr(element, 'data-testid')
            if (dataTestId) {
              push(`${tag}[data-testid="${quote(dataTestId)}"]`)
            }
            const dataTestIdAlt = attr(element, 'data-test-id')
            if (dataTestIdAlt) {
              push(`${tag}[data-test-id="${quote(dataTestIdAlt)}"]`)
            }
            const dataQa = attr(element, 'data-qa')
            if (dataQa) {
              push(`${tag}[data-qa="${quote(dataQa)}"]`)
            }
            const dataAutomationId = attr(element, 'data-automation-id')
            if (dataAutomationId) {
              push(`${tag}[data-automation-id="${quote(dataAutomationId)}"]`)
            }
            const name = attr(element, 'name')
            if (name) {
              push(`${tag}[name="${quote(name)}"]`)
            }
            const autocomplete = attr(element, 'autocomplete')
            if (autocomplete) {
              push(`${tag}[autocomplete="${quote(autocomplete)}"]`)
            }
            const ariaLabel = attr(element, 'aria-label')
            if (ariaLabel) {
              push(`${tag}[aria-label="${quote(ariaLabel)}"]`)
            }
            const placeholder = attr(element, 'placeholder')
            if (placeholder) {
              push(`${tag}[placeholder="${quote(placeholder)}"]`)
            }
            push(`xpath=${xpathForElement(element)}`)
            return candidates
          }
          const mergeSelectorCandidates = (...candidateGroups) => {
            const merged = []
            for (const candidateGroup of candidateGroups) {
              for (const candidate of candidateGroup || []) {
                if (candidate && !merged.includes(candidate)) {
                  merged.push(candidate)
                }
              }
            }
            return merged
          }
          const selectorFor = (element) => {
            const selectors = selectorCandidatesFor(element)
            return selectors[0] || `xpath=${xpathForElement(element)}`
          }
          const associatedChoiceLabel = (element) => {
            const labels = element.labels ? Array.from(element.labels) : []
            if (labels.length) {
              return labels[0]
            }
            if (element.id) {
              const explicitLabel = document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
              if (explicitLabel) {
                return explicitLabel
              }
            }
            return element.closest('label')
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
          const choiceGroupHeadingElement = (container, optionLabels = []) => {
            if (!container) {
              return null
            }
            const optionLabelSet = new Set(
              optionLabels.map((value) => compress(value).toLowerCase()).filter(Boolean)
            )
            const directHeading = Array.from(container.children || []).find((child) => {
              if (!isVisible(child)) {
                return false
              }
              const tag = child.tagName.toLowerCase()
              if (!['legend', 'label', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p'].includes(tag)) {
                return false
              }
              const candidateText = text(child)
              return Boolean(candidateText) && !optionLabelSet.has(candidateText.toLowerCase())
            })
            if (directHeading) {
              return directHeading
            }
            const labelledBy = attr(container, 'aria-labelledby')
            if (labelledBy) {
              const labelledByElements = labelledBy
                .split(' ')
                .map((id) => document.getElementById(id))
                .filter(Boolean)
              if (labelledByElements.length) {
                return labelledByElements[0]
              }
            }
            return null
          }
          const choiceGroupHeading = (container, optionLabels = []) => {
            const headingElement = choiceGroupHeadingElement(container, optionLabels)
            return headingElement ? text(headingElement) : attr(container, 'aria-label')
          }
          const choiceGroupRequired = (container, inputs = [], optionLabels = []) => {
            if (
              inputs.some((input) => input.required || attr(input, 'aria-required') === 'true')
            ) {
              return true
            }
            if (attr(container, 'aria-required') === 'true' || /required/i.test(attr(container, 'class'))) {
              return true
            }
            const headingElement = choiceGroupHeadingElement(container, optionLabels)
            return Boolean(
              headingElement &&
                (attr(headingElement, 'aria-required') === 'true' ||
                  /required/i.test(attr(headingElement, 'class')))
            )
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
              role: attr(element, 'role') || null,
              placeholder: attr(element, 'placeholder') || null,
              label,
              question_text: question,
              required,
              section: sectionText(element) || null,
              selector: selectorFor(element),
              selector_candidates: selectorCandidatesFor(element),
              ...extra,
            }
          }
          const choiceOptionRecord = (element) => {
            const tag = element.tagName.toLowerCase()
            const inputType = tag === 'input' ? (attr(element, 'type') || 'text').toLowerCase() : tag
            const choiceLabelElement =
              tag === 'input' && ['radio', 'checkbox'].includes(inputType)
                ? associatedChoiceLabel(element)
                : null
            const optionLabel =
              text(choiceLabelElement) ||
              labelText(element) ||
              attr(element, 'aria-label') ||
              text(element) ||
              attr(element, 'value') ||
              attr(element, 'data-value')
            const optionValue =
              attr(element, 'value') ||
              attr(element, 'data-value') ||
              attr(element, 'data-key') ||
              optionLabel ||
              'option'
            const choiceLabelSelectors = choiceLabelElement
              ? mergeSelectorCandidates(
                  attr(choiceLabelElement, 'for') ? [`label[for="${quote(attr(choiceLabelElement, 'for'))}"]`] : [],
                  selectorCandidatesFor(choiceLabelElement)
                )
              : []
            const optionSelectors = mergeSelectorCandidates(
              choiceLabelSelectors,
              selectorCandidatesFor(element)
            )
            return {
              label: optionLabel || 'Option',
              value: optionValue,
              selector: optionSelectors[0] || selectorFor(element),
              selector_candidates: optionSelectors,
            }
          }
          const listboxForElement = (element) => {
            const controlledIds = [attr(element, 'aria-controls'), attr(element, 'aria-owns')]
              .flatMap((value) => value.split(' ').filter(Boolean))
            for (const id of controlledIds) {
              const controlled = document.getElementById(id)
              if (controlled) {
                return controlled
              }
            }
            return null
          }
          const seen = new Set()

          const groupedRecords = new Map()
          const output = []
          for (const element of Array.from(document.querySelectorAll('input, textarea, select'))) {
            const tag = element.tagName.toLowerCase()
            const inputType = tag === 'input' ? (attr(element, 'type') || 'text').toLowerCase() : tag
            if (inputType === 'hidden' || attr(element, 'aria-hidden') === 'true' || !isVisible(element)) {
              continue
            }
            seen.add(element)

            if (inputType === 'radio') {
              const optionRecord = choiceOptionRecord(element)
              const groupKey = `radio:${attr(element, 'name') || attr(element, 'id') || selectorFor(element)}`
              const groupContainer = element.closest('fieldset')
              const groupLabel = choiceGroupHeading(groupContainer, [optionRecord.label])
              const group = groupedRecords.get(groupKey) || {
                ...makeBaseRecord(groupContainer || element, {
                  field_type: 'radio',
                  input_type: groupContainer ? 'radiogroup' : 'radio',
                  html_name: attr(element, 'name') || null,
                  html_id: attr(element, 'id') || null,
                  label: groupLabel || labelText(element),
                  question_text: groupLabel || questionText(element, labelText(element)),
                  required: groupContainer
                    ? choiceGroupRequired(groupContainer, [element], [optionRecord.label])
                    : element.required ||
                      attr(element, 'aria-required') === 'true' ||
                      /required/i.test(questionText(element, labelText(element))),
                }),
                options: [],
              }
              group.options.push(optionRecord)
              if (groupContainer) {
                const optionLabels = group.options.map((option) => option.label)
                const updatedLabel = choiceGroupHeading(groupContainer, optionLabels)
                group.label = updatedLabel || group.label
                group.question_text = updatedLabel || group.question_text
                group.required = choiceGroupRequired(groupContainer, [element], optionLabels)
              }
              groupedRecords.set(groupKey, group)
              continue
            }

            if (inputType === 'checkbox' && attr(element, 'name')) {
              const optionRecord = choiceOptionRecord(element)
              const groupKey = `checkbox:${attr(element, 'name')}`
              const count = document.querySelectorAll(
                `input[type="checkbox"][name="${CSS.escape(attr(element, 'name'))}"]`
              ).length
              if (count > 1) {
                const groupContainer = element.closest('fieldset')
                const groupLabel = choiceGroupHeading(groupContainer, [optionRecord.label])
                const group = groupedRecords.get(groupKey) || {
                  ...makeBaseRecord(groupContainer || element, {
                    field_type: 'checkbox',
                    input_type: groupContainer ? 'checkboxgroup' : 'checkbox',
                    html_name: attr(element, 'name') || null,
                    html_id: attr(element, 'id') || null,
                    label: groupLabel || labelText(element),
                    question_text: groupLabel || questionText(element, labelText(element)),
                    required: groupContainer
                      ? choiceGroupRequired(groupContainer, [element], [optionRecord.label])
                      : element.required ||
                        attr(element, 'aria-required') === 'true' ||
                        /required/i.test(questionText(element, labelText(element))),
                  }),
                  options: [],
                }
                group.options.push(optionRecord)
                if (groupContainer) {
                  const optionLabels = group.options.map((option) => option.label)
                  const updatedLabel = choiceGroupHeading(groupContainer, optionLabels)
                  group.label = updatedLabel || group.label
                  group.question_text = updatedLabel || group.question_text
                  group.required = choiceGroupRequired(groupContainer, [element], optionLabels)
                }
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
                  selector_candidates: selectorCandidatesFor(element),
                })),
              })
              continue
            }

            output.push({
              ...makeBaseRecord(element),
              options: [],
            })
          }

          for (const fieldset of Array.from(document.querySelectorAll('fieldset'))) {
            if (!isVisible(fieldset)) {
              continue
            }
            const groupedChoiceInputs = new Map()
            for (const input of Array.from(
              fieldset.querySelectorAll('input[type="radio"], input[type="checkbox"]')
            )) {
              const inputType = (attr(input, 'type') || '').toLowerCase()
              if (!inputType || attr(input, 'aria-hidden') === 'true') {
                continue
              }
              const groupKey = `${inputType}:${attr(input, 'name') || attr(input, 'id') || selectorFor(fieldset)}`
              const group = groupedChoiceInputs.get(groupKey) || []
              group.push(input)
              groupedChoiceInputs.set(groupKey, group)
            }

            for (const [groupKey, inputs] of groupedChoiceInputs.entries()) {
              if (groupedRecords.has(groupKey)) {
                continue
              }
              const inputType = (attr(inputs[0], 'type') || 'radio').toLowerCase()
              const options = inputs.map((input) => choiceOptionRecord(input))
              const label = choiceGroupHeading(fieldset, options.map((option) => option.label))
              if (!label && options.length < 2) {
                continue
              }
              groupedRecords.set(groupKey, {
                ...makeBaseRecord(fieldset, {
                  field_type: inputType,
                  input_type: `${inputType}group`,
                  html_name: attr(inputs[0], 'name') || null,
                  html_id: attr(inputs[0], 'id') || null,
                  label,
                  question_text: label || text(fieldset),
                  required: choiceGroupRequired(fieldset, inputs, options.map((option) => option.label)),
                }),
                options,
              })
            }
          }

          for (const element of Array.from(
            document.querySelectorAll('[role="combobox"], button[aria-haspopup="listbox"], [aria-haspopup="listbox"][aria-controls]')
          )) {
            if (seen.has(element) || !isVisible(element) || ['input', 'textarea', 'select'].includes(element.tagName.toLowerCase())) {
              continue
            }
            seen.add(element)
            const listbox = listboxForElement(element)
            const optionNodes = listbox ? Array.from(listbox.querySelectorAll('[role="option"]')) : []
            output.push({
              ...makeBaseRecord(element, {
                field_type: 'select',
                input_type: attr(element, 'role') || 'combobox',
              }),
              options: optionNodes.map((option) => choiceOptionRecord(option)),
            })
          }

          for (const group of Array.from(document.querySelectorAll('[role="radiogroup"]'))) {
            if (seen.has(group) || !isVisible(group)) {
              continue
            }
            seen.add(group)
            const optionNodes = Array.from(group.querySelectorAll('[role="radio"]'))
            output.push({
              ...makeBaseRecord(group, {
                field_type: 'radio',
                input_type: 'radiogroup',
              }),
              options: optionNodes.map((option) => choiceOptionRecord(option)),
            })
          }

          for (const group of Array.from(document.querySelectorAll('[role="group"]'))) {
            if (seen.has(group) || !isVisible(group)) {
              continue
            }
            const optionNodes = Array.from(group.querySelectorAll('[role="checkbox"]'))
            if (optionNodes.length === 0) {
              continue
            }
            seen.add(group)
            output.push({
              ...makeBaseRecord(group, {
                field_type: 'checkbox',
                input_type: 'checkboxgroup',
              }),
              options: optionNodes.map((option) => choiceOptionRecord(option)),
            })
          }

          return [...output, ...Array.from(groupedRecords.values())]
        }
        """
    )
    raw_fields = _augment_combobox_fields(page, raw_fields)
    raw_fields = [item for item in raw_fields if not _is_placeholder_shadow_input(item)]
    return [_to_field_state(item, index) for index, item in enumerate(raw_fields)]


def _augment_combobox_fields(page, raw_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in raw_fields:
        if item.get("role") != "combobox":
            continue
        options = _collect_combobox_options(page, item)
        if not options:
            continue
        item["field_type"] = "select"
        item["input_type"] = "combobox"
        item["options"] = options
    return raw_fields


def _collect_combobox_options(page, item: dict[str, Any]) -> list[dict[str, Any]]:
    selector = str(item.get("selector") or "").strip()
    if not selector:
        return []

    try:
        locator = page.locator(selector).first
        if locator.count() == 0 or not locator.is_visible():
            return []
        locator.click(timeout=3000)
        page.wait_for_timeout(200)
        options = page.evaluate(
            """
            ({ selector, htmlId }) => {
              const visible = (element) => {
                const style = window.getComputedStyle(element)
                const rect = element.getBoundingClientRect()
                return (
                  style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  rect.width > 0 &&
                  rect.height > 0
                )
              }
              const compress = (value) => (value || '').replace(/\\s+/g, ' ').trim()
              const quote = (value) => String(value).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\\\"')
              const attr = (element, name) => compress(element.getAttribute(name))
              const text = (element) => compress(element?.innerText || element?.textContent || '')
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
              const selectorCandidatesFor = (element) => {
                const tag = element.tagName.toLowerCase()
                const candidates = []
                const push = (candidate) => {
                  if (candidate && !candidates.includes(candidate)) {
                    candidates.push(candidate)
                  }
                }
                if (element.id) {
                  push(`#${CSS.escape(element.id)}`)
                }
                const dataTestId = attr(element, 'data-testid')
                if (dataTestId) {
                  push(`${tag}[data-testid="${quote(dataTestId)}"]`)
                }
                const dataQa = attr(element, 'data-qa')
                if (dataQa) {
                  push(`${tag}[data-qa="${quote(dataQa)}"]`)
                }
                const dataValue = attr(element, 'data-value')
                if (dataValue) {
                  push(`${tag}[data-value="${quote(dataValue)}"]`)
                }
                const ariaLabel = attr(element, 'aria-label')
                if (ariaLabel) {
                  push(`${tag}[aria-label="${quote(ariaLabel)}"]`)
                }
                push(`xpath=${xpathForElement(element)}`)
                return candidates
              }
              const selectorFor = (element) => selectorCandidatesFor(element)[0]
              const input = document.querySelector(selector)
              if (!input) {
                return []
              }

              const candidateIds = []
              const pushId = (value) => {
                if (value && !candidateIds.includes(value)) {
                  candidateIds.push(value)
                }
              }
              const controls = [input.getAttribute('aria-controls'), input.getAttribute('aria-owns')]
                .filter(Boolean)
                .flatMap((value) => value.split(' ').map((part) => part.trim()).filter(Boolean))
              for (const value of controls) {
                pushId(value)
              }
              if (htmlId) {
                pushId(`react-select-${htmlId}-listbox`)
              }

              const listboxes = candidateIds
                .map((id) => document.getElementById(id))
                .filter((element) => element && visible(element))
              const visibleListboxes = listboxes.length
                ? listboxes
                : Array.from(document.querySelectorAll('[role="listbox"]')).filter((element) => visible(element))

              const optionNodes = visibleListboxes.length
                ? visibleListboxes.flatMap((listbox) => Array.from(listbox.querySelectorAll('[role="option"]')))
                : Array.from(document.querySelectorAll('[role="option"]')).filter((element) => visible(element))

              const results = []
              const seen = new Set()
              for (const option of optionNodes) {
                const label = text(option)
                const value = attr(option, 'data-value') || attr(option, 'value') || label
                if (!label || seen.has(`${label}::${value}`)) {
                  continue
                }
                seen.add(`${label}::${value}`)
                results.push({
                  label,
                  value,
                  selector: selectorFor(option),
                  selector_candidates: selectorCandidatesFor(option),
                })
              }
              return results
            }
            """,
            {"selector": selector, "htmlId": item.get("html_id")},
        )
    except PlaywrightError:
        return []
    finally:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(50)
        except PlaywrightError:
            pass
    return options


def _is_placeholder_shadow_input(item: dict[str, Any]) -> bool:
    if item.get("role") != "combobox":
        return False
    if item.get("html_id") or item.get("html_name"):
        return False
    label = str(item.get("label") or "").strip()
    question_text = str(item.get("question_text") or "").strip().lower()
    return not label and question_text in {"select...", "select"}


def _to_field_state(item: dict[str, Any], index: int) -> WorkerFieldState:
    field_id = _build_field_id(item, index)
    options = [
        WorkerFieldOption(
            label=str(option.get("label") or "Option"),
            value=str(option.get("value") or ""),
            selector=str(option.get("selector") or item.get("selector") or ""),
            selector_candidates=[
                str(candidate)
                for candidate in (
                    option.get("selector_candidates")
                    or item.get("selector_candidates")
                    or [option.get("selector") or item.get("selector") or ""]
                )
                if str(candidate or "").strip()
            ],
        )
        for option in item.get("options", [])
    ]
    return WorkerFieldState(
        field_id=field_id,
        label=str(item.get("label") or ""),
        question_text=str(item.get("question_text") or ""),
        selector=str(item.get("selector") or ""),
        selector_candidates=[
            str(candidate)
            for candidate in (item.get("selector_candidates") or [item.get("selector") or ""])
            if str(candidate or "").strip()
        ],
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

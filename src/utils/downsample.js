/**
 * LTTB (Largest Triangle Three Buckets) 降采样算法
 * 在保持数据趋势的同时减少数据点数量
 * 
 * @param {Array} data - 原始数据数组，每项为 {x, y} 或 [x, y] 格式
 * @param {number} threshold - 目标数据点数量
 * @returns {Array} 降采样后的数据
 */
export function lttbDownsample(data, threshold) {
  if (!data || data.length <= threshold) return data

  const length = data.length
  const sampled = []

  // 始终保留第一个点
  sampled.push(data[0])

  const bucketSize = (length - 2) / (threshold - 2)

  let prevIndex = 0

  for (let i = 0; i < threshold - 2; i++) {
    // 计算当前桶的范围
    const rangeStart = Math.floor((i + 1) * bucketSize) + 1
    const rangeEnd = Math.min(Math.floor((i + 2) * bucketSize) + 1, length - 1)

    // 计算下一个桶的平均值（作为三角形的第三个点）
    const nextBucketStart = Math.floor((i + 2) * bucketSize) + 1
    const nextBucketEnd = Math.min(Math.floor((i + 3) * bucketSize) + 1, length - 1)

    let avgX = 0, avgY = 0, count = 0
    for (let j = nextBucketStart; j < nextBucketEnd && j < length; j++) {
      avgX += j
      avgY += getY(data[j])
      count++
    }
    if (count === 0) { avgX = nextBucketStart; avgY = getY(data[Math.min(nextBucketStart, length - 1)]); count = 1 }
    avgX /= count
    avgY /= count

    // 在当前桶中找到与前一个点和平均点构成最大三角形面积的点
    let maxArea = -1
    let maxIndex = rangeStart
    const prevY = getY(data[prevIndex])

    for (let j = rangeStart; j < rangeEnd && j < length; j++) {
      const area = Math.abs(
        (prevIndex - avgX) * (getY(data[j]) - prevY) -
        (prevIndex - j) * (avgY - prevY)
      )
      if (area > maxArea) {
        maxArea = area
        maxIndex = j
      }
    }

    sampled.push(data[maxIndex])
    prevIndex = maxIndex
  }

  // 始终保留最后一个点
  sampled.push(data[length - 1])

  return sampled
}

/**
 * 简单降采样 - 对平行数组进行降采样
 * 适用于 dates[] 和 values[] 分离存储的场景
 * 
 * @param {Array} dates - 日期数组
 * @param {Array} values - 数值数组（与 dates 等长）
 * @param {number} maxPoints - 最大数据点数，默认 500
 * @returns {{dates: Array, values: Array}} 降采样后的数据
 */
export function downsampleParallel(dates, values, maxPoints = 500) {
  if (!dates || dates.length <= maxPoints) {
    return { dates, values }
  }

  // 构造合并数组用于 LTTB
  const combined = dates.map((d, i) => ({ x: i, y: values[i], date: d }))
  const sampled = lttbDownsample(combined, maxPoints)

  return {
    dates: sampled.map(p => p.date),
    values: sampled.map(p => p.y)
  }
}

/**
 * 对多条线的数据进行降采样（共享 x 轴索引）
 * 
 * @param {Array} dates - 共享的日期数组
 * @param {Object} seriesMap - { seriesName: valuesArray }
 * @param {number} maxPoints - 最大数据点数
 * @returns {{dates: Array, series: Object}} 降采样后的数据
 */
export function downsampleMultiSeries(dates, seriesMap, maxPoints = 500) {
  if (!dates || dates.length <= maxPoints) {
    return { dates, series: seriesMap }
  }

  // 使用均匀采样索引（多线共享同一 x 轴时 LTTB 不适用，改用均匀采样保留首尾）
  const step = (dates.length - 1) / (maxPoints - 1)
  const indices = []
  for (let i = 0; i < maxPoints; i++) {
    indices.push(Math.round(i * step))
  }

  const sampledDates = indices.map(i => dates[i])
  const sampledSeries = {}
  for (const [name, values] of Object.entries(seriesMap)) {
    sampledSeries[name] = indices.map(i => values[i])
  }

  return { dates: sampledDates, series: sampledSeries }
}

// 辅助函数：获取数据点的 y 值
function getY(point) {
  if (typeof point === 'number') return point
  if (point && typeof point.y === 'number') return point.y
  if (Array.isArray(point)) return point[1]
  return 0
}
